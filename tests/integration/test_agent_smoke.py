import sys
import pytest
from langchain_core.messages import HumanMessage, AIMessage
from spotify_agent.graph import app
from spotify_agent.schemas import IntentPlan, ToolPlan
from utils.loggings import setup_logging

# Initialize logging early
if __name__ == "__main__":
    setup_logging(mode="test", log_name="agent_smoke_manual")

@pytest.mark.integration
def test_graph_smoke_mock(mock_llm_chain):
    """Test the graph using mocked LLM."""
    print("\n--- Testing Graph with Mocked LLM ---")
    user_input = "Show my top artists"
    
    # 1. Mock intent_parser
    mock_intent_plan = IntentPlan(
        intent_type="factual_query",
        reasoning="Mock reasoning",
        tool_plan=[ToolPlan(tool_name="get_top_artists", reasoning="Test")]
    )
    mock_llm_chain.with_structured_output.return_value.invoke.return_value = mock_intent_plan
    
    # 2. Mock data_fetch
    mock_tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "get_top_artists", "args": {"limit": 5}, "id": "call_1"}]
    )
    mock_llm_chain.bind_tools.return_value.invoke.return_value = mock_tool_call_msg
    
    # 3. Mock analyst_node
    mock_llm_chain.invoke.return_value = AIMessage(content="Mock analysis for get_top_artists: [data]")
    
    final_state = app.invoke(
        {
            "input": user_input,
            "messages": [HumanMessage(content=user_input)]
        }
    )
    
    assert final_state.get("intent") == "factual_query"
    assert "Mock analysis" in final_state.get("final_response")
    print("Mock tool test passed!")

@pytest.mark.integration
def test_graph_smoke_out_of_scope(mock_llm_chain):
    """Test the graph with an out-of-scope input."""
    print("\n--- Testing Graph with Out of Scope ---")
    
    user_input = "What is the weather?"
    
    # Mock intent_parser for other
    mock_intent_plan = IntentPlan(
        intent_type="other",
        reasoning="I am a Spotify assistant.",
        tool_plan=[]
    )
    mock_llm_chain.with_structured_output.return_value.invoke.return_value = mock_intent_plan
    
    # Mock analyst_node (or it might just use plan.reasoning if no tools)
    # In my refined analyst_node, it uses response_content = plan.reasoning if no tools.
    
    final_state = app.invoke(
        {
            "input": user_input,
            "messages": [HumanMessage(content=user_input)]
        }
    )
    
    assert final_state.get("intent") == "other"
    assert "I am a Spotify assistant" in final_state.get("final_response")
    print("Out of scope test passed!")
