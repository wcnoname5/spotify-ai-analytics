from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes import intent_parser, data_fetch, analyst_node, should_continue

def build_app():
    """Create the LangGraph workflow."""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("IntentParser", intent_parser)
    workflow.add_node("ToolExecute", data_fetch)
    workflow.add_node("Analyst", analyst_node)
    
    # Set entry point
    workflow.set_entry_point("IntentParser")
    # Add edges
    workflow.add_conditional_edges(
        "IntentParser",
        should_continue,
        {
            "continue": "ToolExecute",
            "end": "Analyst"
        }
    )
    
    workflow.add_edge("ToolExecute", "Analyst")
    workflow.add_edge("Analyst", END)
    
    return workflow.compile()
# Compiled Graph instance
app = build_app()
