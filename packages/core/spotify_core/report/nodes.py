"""Graph nodes for the report graph: drafter, reviewer, route_after_review.

make_report_nodes(tools) returns the three callables bound to the tool list via
closure — the same factory pattern used by spotify_core/agent/nodes.py.
"""
from loguru import logger
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from .prompts import REVIEWER_RUBRIC, compose_drafter_system
from .state import ReportState, ReviewVerdict, extract_tool_log

# Hard caps that guarantee the graph terminates.
_MAX_TOOL_ITERATIONS = 10
_MAX_REVISIONS = 2


def make_report_nodes(tools: list):
    """Return (drafter_node, reviewer_node, route_after_review) bound to tools."""
    tools_by_name = {t.name: t for t in tools}

    def drafter_node(state: ReportState, config: RunnableConfig) -> dict:
        """Write (or revise) the report, calling data tools in a bounded loop."""
        logger.info("drafter_node: style={} period_type={} revision={}",
                    state["style"], state.get("period_type", "custom"),
                    state["revision_count"])
        model = config["configurable"]["model"]
        model_with_tools = model.bind_tools(tools)

        system = compose_drafter_system(
            period_type=state.get("period_type", "custom"),
            style=state["style"],
        )

        period_label = {
            "weekly": "上一個已結束的週次",
            "monthly": "上一個已結束的月份",
            "custom": "使用者自訂的時間區間",
        }.get(state.get("period_type", "custom"), "使用者自訂的時間區間")

        user = (
            f"請分析使用者從 {state['start_date']} 到 {state['end_date']} "
            f"（{period_label}）的聽歌資料，依系統提示中對應 period_type 的"
            f"框架呼叫工具並寫出文章。"
        )
        
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        if state["review_feedback"]:
            messages.append(HumanMessage(content=(
                f"你上一版的草稿：\n{state['draft']}\n\n"
                f"編輯的修改意見，請據此改寫：\n{state['review_feedback']}"
            )))

        draft = ""
        for i in range(_MAX_TOOL_ITERATIONS):
            response = model_with_tools.invoke(messages, config=config)
            messages.append(response)
            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                draft = response.content
                break
            logger.debug("drafter_node: iteration {}, {} tool call(s)",
                         i+1, len(tool_calls))
            for tool_call in tool_calls:
                report_tool = tools_by_name.get(tool_call["name"])
                if report_tool is None:
                    logger.warning("drafter_node: unknown tool {}",
                                   tool_call["name"])
                    messages.append(ToolMessage(
                        content=f"Unknown tool: {tool_call['name']}",
                        tool_call_id=tool_call["id"],
                        status="error",
                    ))
                    continue
                messages.append(report_tool.invoke(tool_call, config=config))
        else:
            logger.warning("drafter_node: hit tool-iteration cap")
            draft = next(
                (m.content for m in reversed(messages)
                 if isinstance(m, AIMessage) and m.content),
                state["draft"],
            )

        tool_log = extract_tool_log(messages)
        logger.info("drafter_node: draft {} chars, {} tool calls",
                    len(draft), len(tool_log))
        return {"draft": draft, "tool_log": tool_log}

    def reviewer_node(state: ReportState, config: RunnableConfig) -> dict:
        """Judge the draft; approve or return revision feedback."""
        logger.info("reviewer_node: reviewing revision {}",
                    state["revision_count"])
        model = config["configurable"]["model"]
        reviewer = model.with_structured_output(ReviewVerdict)

        tool_summary = "\n".join(
            f"- {r.name}({r.args}) -> {'OK' if r.success else 'ERROR'}: {r.result}"
            for r in state["tool_log"]
        ) or "（沒有工具呼叫紀錄）"
        messages = [
            SystemMessage(content=REVIEWER_RUBRIC),
            HumanMessage(content=(
                f"指定風格：{state['style']}\n"
                f"指定 period_type：{state.get('period_type', 'custom')}\n"
                f"分析區間：{state['start_date']} ~ {state['end_date']}\n\n"
                f"草稿：\n{state['draft']}\n\n"
                f"草稿作者實際取得的資料：\n{tool_summary}"
            )),
        ]
        verdict: ReviewVerdict = reviewer.invoke(messages, config=config)
        if verdict.approved:
            logger.info("reviewer_node: approved")
            return {
                "approved": True,
                "review_feedback": "",
                "final_report": state["draft"],
            }
        logger.info("reviewer_node: rejected — {}", verdict.feedback[:120])
        return {
            "approved": False,
            "review_feedback": verdict.feedback,
            "revision_count": state["revision_count"] + 1,
            "final_report": state["draft"],
        }

    def route_after_review(state: ReportState) -> str:
        """Approved or revision cap reached -> end; otherwise revise."""
        if state["approved"] or state["revision_count"] >= _MAX_REVISIONS:
            logger.info("route_after_review: end (approved={}, revisions={})",
                        state["approved"], state["revision_count"])
            return "end"
        logger.info("route_after_review: back to drafter")
        return "drafter"

    return drafter_node, reviewer_node, route_after_review
