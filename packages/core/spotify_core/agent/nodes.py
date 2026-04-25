import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from langchain_core.messages import ToolMessage, AIMessage

from .state import AgentState
from .schemas import IntentPlan, ToolPlan
from .prompts import INTENT_PARSER_SYSTEM_PROMPT

def make_nodes(llm, tools_list: list, tool_executor: dict):
    """Factory that returns graph node functions bound to the given resources via closure."""

    def intent_parser(state: AgentState) -> Dict[str, Any]:
        """Parse the user's intent and generate a strategic execution plan."""
        logger = logging.getLogger(f'{__name__}.intent_parser')
        logger.info(f"Planning for input: {state['input']}")

        if llm is None:
            error_msg = "AI model not initialized. Please check your API key."
            return {"intent": "other", "messages": [AIMessage(content=error_msg)], "final_response": error_msg}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_system_prompt = INTENT_PARSER_SYSTEM_PROMPT + f"\n\nCurrent date and time: {now}."
        plan = llm.with_structured_output(IntentPlan).invoke([
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": state["input"]}
        ])

        if not plan:
            raise ValueError("Failed to parse intent plan.")

        logger.info(f"Intent parsed: {plan.intent_type} | Tools: {[tp.tool_name for tp in plan.tool_plan]}")
        return {"intent": plan.intent_type, "plan": plan, "messages": [AIMessage(content=f"Strategy: {plan.reasoning}")]}

    def data_fetch(state: AgentState) -> Dict[str, Any]:
        """Execute tools based on the plan."""
        logger = logging.getLogger(f'{__name__}.data_fetch')
        plan = state.get("plan")
        if not plan or not plan.tool_plan:
            return {"messages": []}

        planned_tool_names = [tp.tool_name for tp in plan.tool_plan]
        available_tools = [t for t in tools_list if t.name in planned_tool_names]
        if not available_tools:
            return {"messages": [AIMessage(content="Planned tools are unavailable.")]}

        llm_with_tools = llm.bind_tools(available_tools)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response = llm_with_tools.invoke([
            {"role": "system", "content": f"You are a Spotify Tool Specialist. Context: {plan.reasoning}. Time: {now}. Only call provided tools."},
            {"role": "user", "content": state["input"]}
        ])

        results, tool_messages = [], []
        if hasattr(response, 'tool_calls') and response.tool_calls:
            tool_messages.append(response)
            for i, tool_call in enumerate(response.tool_calls):
                tool_name = tool_call["name"]
                if tool_name not in planned_tool_names:
                    logger.warning(f"Hallucinated tool call: {tool_name}")
                    continue
                tool_obj = tool_executor.get(tool_name)
                if tool_obj is None:
                    logger.error(f"Tool '{tool_name}' in plan but not in executor. Skipping.")
                    continue
                call_id = tool_call.get("id", f"call_{i}")
                retrieved_data, last_error = None, None
                for attempt in range(3):
                    try:
                        retrieved_data = tool_obj.invoke(tool_call["args"])
                        break
                    except Exception as e:
                        last_error = str(e)
                        if attempt == 2:
                            retrieved_data = f"Error after 3 attempts: {last_error}"
                obs_str = str(retrieved_data)
                if len(obs_str) > 1000:
                    obs_str = obs_str[:1000] + "... [truncated]"
                tool_messages.append(ToolMessage(content=obs_str, name=tool_name, tool_call_id=call_id))
                results.append(retrieved_data)
                logger.info(f"Tool {tool_name}: success={last_error is None}")
        return {"messages": tool_messages, "tool_results": results}

    def analyst_node(state: AgentState) -> Dict[str, Any]:
        """Synthesize the final response."""
        logger = logging.getLogger(f'{__name__}.analyst_node')
        if state.get("final_response"):
            return {"final_response": state["final_response"]}

        intent = state.get("intent", "other")
        plan = state.get("plan")

        system_prompts = {
            "factual_query": "You are a Spotify analytics assistant. Be direct, use bullet points.",
            "insight_analysis": f"You are a Spotify music critic. Tell a story. Focus: {plan.analysis_focus if plan else ''}",
            "recommendation": "You are a Spotify recommendation expert. Suggest music based on listening history.",
        }
        system_prompt = system_prompts.get(intent, "You are a Spotify analytics assistant.")

        tool_messages = [m for m in state.get("messages", []) if isinstance(m, ToolMessage)]

        if intent == "other" and (not plan or not plan.tool_plan):
            response_content = plan.reasoning if plan else "I'm a Spotify analytics assistant and can't help with that."
        else:
            data_str = ""
            if tool_messages:
                tool_results = state.get("tool_results", [])
                for i, msg in enumerate(tool_messages):
                    result = tool_results[i] if i < len(tool_results) else msg.content
                    formatted = json.dumps(result, indent=2) if isinstance(result, (list, dict)) else str(result)
                    data_str += f"### Tool: {getattr(msg, 'name', f'Tool_{i}')}\n{formatted}\n\n"

            messages = [{"role": "system", "content": system_prompt}]
            if data_str:
                messages.append({"role": "user", "content": f"Spotify data:\n<data>\n{data_str}\n</data>"})
            messages.append({"role": "user", "content": f"Address my request: {state['input']}"})
            response_content = llm.invoke(messages).content

        logger.info(f"[Monitoring] Node: analyst_node | Intent: {intent} | Tools Used: {len(tool_messages) > 0}")
        logger.info(f"Final response length: {len(response_content)}")
        return {"final_response": response_content}

    def should_continue(state: AgentState) -> str:
        """Route: continue to ToolExecute or go to Analyst."""
        plan = state.get("plan")
        if plan and plan.tool_plan:
            return "continue"
        return "end"

    return intent_parser, data_fetch, analyst_node, should_continue
