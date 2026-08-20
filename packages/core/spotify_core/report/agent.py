"""The report agent: a date range in, a markdown article out.

`generate_report` is this module's entire public surface. There is deliberately no
graph and no reviewer — one bounded `create_agent` loop writes the article, and
`prompts.py` carries the quality bar.
"""
from loguru import logger
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .observability import langfuse_session
from .prompts import report_system_prompt, report_struct
from .tools import make_report_tools

# Hard cap that guarantees the agent terminates.
_MAX_MODEL_CALLS = 10


def generate_report(
    *,
    style: str,
    start_date: str,
    end_date: str,
    db_path: str,
    model: BaseChatModel,
    period_type: str = "weekly",
) -> str:
    """Write one listening-analysis article and return it as markdown.

    Args:
        style: One of "listening_review", "roast".
        start_date: ISO "YYYY-MM-DD" range start.
        end_date: ISO "YYYY-MM-DD" range end.
        db_path: Path to history.db.
        model: The chat model that writes the article.
        period_type: "weekly", "monthly", "quarterly", "yearly", or "custom".

    Raises:
        ModelCallLimitExceededError: The agent spent its whole call budget without
            finishing the article.
        RuntimeError: The agent finished without producing any prose.
    """
    logger.info("generate_report: style={} period_type={} range={}..{}",
                style, period_type, start_date, end_date)

    # ponytail: no reviewer — quality rides on the playbook prompts. If output proves
    # unstable, add one back as an @after_agent(can_jump_to=["model"]) middleware
    # returning Command(goto="model", ...) 
    agent = create_agent(
        model,
        make_report_tools(db_path),
        # raise error instead of return ToolMessage warning exceed tool calls
        middleware=[ModelCallLimitMiddleware(
            run_limit=_MAX_MODEL_CALLS, exit_behavior="error",
        )],
    )

    messages = [
        SystemMessage(content=report_system_prompt(
            playbook=report_struct(period_type), style=style,
        )),
        HumanMessage(content=(
            f"請分析使用者從 {start_date} 到 {end_date} 的歌曲聆聽資料，"
            f"依照系統提示的分析框架呼叫工具並寫出文章。"
        )),
    ]

    with langfuse_session(style=style, period_type=period_type) as callbacks:
        out = agent.invoke({"messages": messages}, config={
            "callbacks": callbacks,
            "run_name": f"report-{style}_{start_date}-{end_date}",
        })["messages"]

    # .text, not .content: Gemini 3.x returns a list of content blocks; .text joins
    # the text parts on every model. Walking backwards because the final message can
    # be a ToolMessage when the agent stops right after a tool call.
    text = next(
        (m.text for m in reversed(out) if isinstance(m, AIMessage) and m.text),
        "",
    )
    if not text:
        # raise error instead of retunring half-written article
        raise RuntimeError(
            f"report agent produced no prose after {len(out)} messages "
            f"(model call limit is {_MAX_MODEL_CALLS})"
        )
    logger.info("generate_report: done — {} chars", len(text))
    return text
