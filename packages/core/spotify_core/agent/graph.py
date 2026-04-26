from typing import Optional
from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes import make_nodes

def build_app(llm, tools_list: list, checkpointer=None, store=None):
    """Build and compile the LangGraph workflow.

    Args:
        llm: LangChain LLM instance (ChatOpenAI or ChatGoogleGenerativeAI)
        tools_list: List of LangChain tools from initialize_tools()
        checkpointer: Optional SqliteSaver for short-term per-thread memory.
        store: Optional SqliteStore for long-term cross-session memory.
    """
    tool_executor = {t.name: t for t in tools_list}
    intent_parser, data_fetch, analyst_node, should_continue = make_nodes(llm, tools_list, tool_executor)

    workflow = StateGraph(AgentState)
    workflow.add_node("IntentParser", intent_parser)
    workflow.add_node("ToolExecute", data_fetch)
    workflow.add_node("Analyst", analyst_node)
    workflow.set_entry_point("IntentParser")
    workflow.add_conditional_edges("IntentParser", should_continue, {"continue": "ToolExecute", "end": "Analyst"})
    workflow.add_edge("ToolExecute", "Analyst")
    workflow.add_edge("Analyst", END)
    return workflow.compile(checkpointer=checkpointer, store=store)
