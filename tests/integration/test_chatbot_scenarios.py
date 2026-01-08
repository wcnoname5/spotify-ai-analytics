import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from langchain_core.messages import HumanMessage

from utils.loggings import setup_logging
# Initialize logging early to capture setup logs from imported modules
if __name__ == "__main__":
    setup_logging(mode="test", log_name="chatbot_scenarios_manual")

from spotify_agent.graph import build_app

def _run_scenario_logic(query, expected_intent, expected_tool, expected_args):
    """Common logic for running a chatbot scenario test."""
    # Mock datetime to return 2026-01-05
    mock_now = datetime(2026, 1, 5, 12, 0, 0)
    
    with patch("spotify_agent.nodes.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        # Ensure strftime works on the mock if needed
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        
        app = build_app()
        
        final_state = app.invoke(
            {
                "input": query,
                "messages": [HumanMessage(content=query)]
            },
            config={"configurable": {"thread_id": "test_thread"}}
        )
        
        # 1. Check intent
        actual_intent = final_state.get("intent")
        assert actual_intent == expected_intent
        
        # 2. Check tool execution in messages
        messages = final_state.get("messages", [])
        tool_call_found = False
        
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == expected_tool:
                        tool_call_found = True
                        # Check args
                        for key, val in expected_args.items():
                            assert tc["args"].get(key) == val
                        break
            if tool_call_found:
                break
        
        assert tool_call_found, f"Tool call for {expected_tool} not found in messages."

@pytest.mark.llm
def test_top_artists_scenario():
    """Scenario: Query for top 3 artists."""
    _run_scenario_logic(
        query="Who are my top 3 favorite artists?", 
        expected_intent="factual_query", 
        expected_tool="get_top_artists", 
        expected_args={"limit": 3}
    )

@pytest.mark.llm
def test_last_year_analysis_scenario():
    """Scenario: Analyze music taste in the last year (2025)."""
    _run_scenario_logic(
        query="Analyze my music taste in last year", 
        expected_intent="insight_analysis", 
        expected_tool="get_top_artists", 
        expected_args={"start_date": "2025-01-01", "end_date": "2025-12-31"}
    )

if __name__ == "__main__":
    print("Starting Manual Scenario Tests...")
    
    print("\n[Case 1] Top 3 Artists Scenario")
    try:
        test_top_artists_scenario()
        print("✓ Case 1 passed!")
    except Exception as e:
        print(f"✗ Case 1 failed: {e}")
    
    print("\nSleeping for 10 seconds between cases to avoid rate limits...")
    time.sleep(10)
    
    print("\n[Case 2] Last Year Analysis Scenario")
    try:
        test_last_year_analysis_scenario()
        print("✓ Case 2 passed!")
    except Exception as e:
        print(f"✗ Case 2 failed: {e}")
    
    print("\nAll scenario tests completed.")
