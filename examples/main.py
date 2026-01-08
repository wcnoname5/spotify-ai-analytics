from utils.loggings import setup_logging
# Configure logging first!
setup_logging()

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from spotify_agent.graph import build_app


def main():
    """Main entry point for the Spotify AI Analytics Agent."""
    # Load environment variables
    load_dotenv()
    
    # Run the graph
    print("=== Starting Spotify Agent ===")
    # example user input:
    user_input = "Show me my top 5 artists and tracks from January 2024"
    # user_input = "Can you recommend some new artists for me according to my taste in last year?"
    
    app = build_app()
    final_state = app.invoke(
        {
            "input": user_input, 
            "messages": [HumanMessage(content=user_input)]
        },
        config={"configurable": {"thread_id": "example_call"}}
    )
    
    print("\n=== Final Response ===")
    print(final_state.get("final_response"))
    print("\n=== Tool Results ===")
    print(final_state.get("tool_results"))

if __name__ == "__main__":
    main()
