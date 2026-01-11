import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from langchain_core.messages import ToolMessage, AIMessage, BaseMessage

from .state import AgentState
from utils.agent_utils import get_resources
from .schemas import IntentPlan, ToolPlan
from .prompts import INTENT_PARSER_SYSTEM_PROMPT
from config.settings import settings 


# Global placeholders for lazy initialization
# (Moved to utils.py)

def intent_parser(state: AgentState) -> Dict[str, Any]:
    """Parse the user's intent and generate a strategic execution plan (without tool args)."""
    llm, _, _ = get_resources()
    logger = logging.getLogger(f'{__name__}.intent_parser')
    logger.info(f"Planning for input: {state['input']}")
    
    # Use the structured output LLM to generate a strategic plan
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_system_prompt = INTENT_PARSER_SYSTEM_PROMPT + f"\n\nCurrent date and time: {now}."
    
    # The Orchestrator only decides WHICH tools and provides high-level REASONING.
    # Argument generation is deferred to the data_fetch node.
    plan = llm.with_structured_output(IntentPlan).invoke([
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": state["input"]}
    ])
    
    if plan:
        logger.info(f"Intent parsed: {plan.intent_type}")
        logger.info(f"Reasoning: {plan.reasoning}")
        if plan.tool_plan:
            for i, tp in enumerate(plan.tool_plan, 1):
                logger.info(f"Tool Selection {i}: {tp.tool_name} (Reason: {tp.reasoning})")
        else:
            logger.info("No tools required for this request.")
    else:
        raise ValueError("Failed to parse intent plan.")
    
    # Log for monitoring replaced with logger
    logger.info(f"[Monitoring] Node: planner | Intent: {plan.intent_type} | Tools: {[tp.tool_name for tp in plan.tool_plan]}")
    
    return {
        "intent": plan.intent_type, 
        "plan": plan,
        "messages": [AIMessage(content=f"Strategy: {plan.reasoning}")], 
    }

def data_fetch(state: AgentState) -> Dict[str, Any]:
    """
    1. Bind specific tools based on the plan.
    2. Use LLM to generate precise tool arguments.
    3. Execute tools with retry/truncation.
    """
    llm, tools_list, tool_executor = get_resources()
    logger = logging.getLogger(f'{__name__}.data_fetch')
    plan = state.get("plan")
    
    if not plan or not plan.tool_plan:
        logger.info("No tools planned for execution")
        return {"messages": []}

    # 1. Filter and Bind Tools
    planned_tool_names = [tp.tool_name for tp in plan.tool_plan]
    available_tools = [t for t in tools_list if t.name in planned_tool_names]
    
    if not available_tools:
        logger.warning(f"Planned tools {planned_tool_names} are not available in tools_list.")
        return {"messages": [AIMessage(content="I planned to use some tools, but they are currently unavailable.")]}

    # 2. Generate Tool Calls using LLM
    # We pass the original input and the strategic focus to help the LLM generate correct args.
    logger.info(f"Generating tool calls with tools: {[t.name for t in available_tools]}")
    llm_with_tools = llm.bind_tools(available_tools)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_instruction = (
        f"You are a Spotify Tool Specialist. Generate precise tool calls to address the user request. "
        f"Context/Focus: {plan.reasoning}. "
        f"Current time: {now}. "
        "Only generate tool calls for the tools provided."
    )
    
    response = llm_with_tools.invoke([
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": state["input"]}
    ])

    # Tool results and messages
    results = []
    tool_messages = []

    # 3. Execute identified tool calls
    if hasattr(response, 'tool_calls') and response.tool_calls:
        # Add the LLM response (with tool_calls) to history
        tool_messages.append(response)
        
        logger.info(f"Toal {len(response.tool_calls)} tools will execute.")
        for i, tool_call in enumerate(response.tool_calls):
            logger.info(f"Executing tool call {i+1}: {tool_call}")
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            
            # Fallback/Safety: Ensure tool was actually in the plan
            if tool_name not in planned_tool_names:
                logger.warning(f"Hallucination detected: LLM called '{tool_name}' which was not in the plan. Skipping.")
                continue

            tool_obj = tool_executor.get(tool_name)
            call_id = tool_call.get("id", f"fetch_step_{i}")
            
            # Retry logic
            max_retries = 3
            last_error = None
            retrieved_data = None
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"Executing '{tool_name}' (Attempt {attempt + 1}/{max_retries}) with args: {tool_args}")
                    retrieved_data = tool_obj.invoke(tool_args)
                    break # Success
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Error in {tool_name}: {last_error}")
                    if attempt == max_retries - 1:
                        retrieved_data = f"Error after {max_retries} attempts: {last_error}"
            
            # Truncate long results
            obs_str = str(retrieved_data)
            if len(obs_str) > 1000:
                logger.warning(f"Truncating result for '{tool_name}' from {len(obs_str)} to 1000 chars")
                obs_str = obs_str[:1000] + "... [Results truncated]"
            
            tool_messages.append(ToolMessage(
                content=obs_str,
                name=tool_name,
                tool_call_id=call_id
            ))
            results.append(retrieved_data)
            
            # Log for monitoring replaced with logger
            logger.info(f"[Monitoring] Node: data_fetch | Tool: {tool_name} | Success: {last_error is None} | Result Size: {len(obs_str)}")
    else:
        logger.warning("No tool calls generated by the LLM in data_fetch.")
        
    return {"messages": tool_messages, "tool_results": results}

def analyst_node(state: AgentState) -> Dict[str, Any]:
    """Generate the final response based on tool results and conversation history."""
    llm, _, _ = get_resources()
    logger = logging.getLogger(f'{__name__}.analyst_node')
    
    intent = state.get("intent", "other")
    plan = state.get("plan")
    analysis_focus = plan.analysis_focus if plan else ""
    logger.info(f"Generating final response for intent: {intent} with analysis focus: {analysis_focus}")
    
    # Prepare system prompt based on intent
    if intent == "factual_query":
        system_prompt = (
            "You are a Spotify analytics assistant. The user wants a factual answer. "
            "Be direct, use bullet points, and avoid unnecessary commentary. "
            "Synthesize the tool results into a clear answer."
        )
    elif intent == "insight_analysis":
        system_prompt = (
            "You are a Spotify music critic and data analyst. The user wants insights and trends. "
            "Interpret the data, compare different aspects, and tell a story. "
            f"Focus on: {analysis_focus}"
        )
    elif intent == "recommendation":
        system_prompt = (
            "You are a Spotify recommendation expert. Based on the user's listening history, "
            "suggest new music they might like. Explain why you are making these recommendations."
        )
    else:
        system_prompt = (
            "You are a Spotify analytics assistant. Provide a helpful response to the user's query."
        )

    # Check if tools were used by looking for ToolMessages in the state
    tool_messages = [m for m in state.get("messages", []) if isinstance(m, ToolMessage)]
    tool_used = len(tool_messages) > 0
    
    data_str = ""
    if tool_used:
        logger.info("Preparing data string from tool messages for analysis")
        tool_results = state.get("tool_results", [])
        for i, msg in enumerate(tool_messages):
            # Use the tool name from the message and the corresponding result
            name = getattr(msg, "name", f"Tool_{i}")
            # let's keep it first
            args = getattr(msg, "args", {}) 
            # Prefer the raw tool_results if available, otherwise use message content
            result = tool_results[i] if i < len(tool_results) else msg.content
            
            # Format the result for the prompt
            if isinstance(result, (list, dict)):
                formatted_result = json.dumps(result, indent=2)
            else:
                formatted_result = str(result)
                
            data_str += f"### Tool: {name}\n{formatted_result}\n\n"
        
    # If no tools were used and intent is 'other', respond directly
    if intent == "other" and (not plan or not plan.tool_plan):
        response_content = plan.reasoning if plan else "I'm sorry, I can't help with that. I'm a Spotify analytics assistant."
    else:
        # Build prompts for the LLM
        user_prompt = f"Here is the retrieved Spotify data for analysis:\n<data>\n{data_str}\n</data>" if tool_used else None
        user_input_prompt = f"Based on the data above, " if tool_used else "" 
        user_input_prompt += f"please address my original request: {state['input']}" 

        logger.info(f"User prompt prepared: {user_prompt[:200] + '...trunctated' if user_prompt else 'No user prompt'}")
        logger.info(f"User input prompt prepared: {user_input_prompt[:200] + '...trunctated' if user_input_prompt else 'No user input prompt'}")

        # Construct message list for LLM
        messages = [{"role": "system", "content": system_prompt}]
        if tool_used:
            messages.append({"role": "user", "content": user_prompt})
        messages.append({"role": "user", "content": user_input_prompt})
        
        # Use the base LLM to synthesize the final answer
        response = llm.invoke(messages)
        response_content = response.content

    # Log for monitoring replaced with logger
    # Logging intent and tool usage BEFORE returning, after synthesizing/calculating result
    logger.info(f"[Monitoring] Node: analyst_node | Intent: {intent} | Tools Used: {tool_used}")
    logger.info(f"Raw response: {response_content}")
    logger.info(f"Final response length: {len(response_content)}") 

    return {"final_response": response_content}

def should_continue(state: AgentState) -> str:
    """
    Determine whether to continue to tool execution or go to analyst.
    """
    logger = logging.getLogger(f'{__name__}.edge_logic')
    plan = state.get("plan")
    
    # If the Planner generated a tool plan, continue to ToolExecute
    if plan and plan.tool_plan:
        logger.info(f"{len(plan.tool_plan)} tools planned, routing to ToolExecute")
        return "continue"
    
    # Otherwise, go to Analyst
    logger.info("No tools planned, routing to Analyst")
    return "end"
