import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from spotify_agent.graph import build_app
from utils.agent_utils import resolve_api_key, validate_api_key

def render_chatbot():
    st.header("Spotify Data Chatbot")
    
    # Check for API Key early to warn user
    provider = st.session_state.get("model_provider", "Gemini")
    api_key, _ = resolve_api_key(provider)
    validation_status = validate_api_key(provider, api_key) if api_key else "unchecked"
    
    can_chat = True
    if not api_key:
        st.warning(f"⚠️ **{provider} API key not found.** You can still see the interface, but the agent won't be able to respond until you configure it in the sidebar.")
        can_chat = False
    elif validation_status == "invalid":
        st.error(f"❌ **Invalid {provider} API key.** The agent cannot function with an invalid key. Please update it in the sidebar.")
        can_chat = False
    elif validation_status == "network_error":
        st.warning(f"⚠️ **{provider} Connection error.** I'm having trouble reaching the AI service. Please check your network or try again later.")
        can_chat = False

    # Initialize session state for messages if not exists
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Display chat history in a scrollable container
    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.messages:
            if isinstance(message, HumanMessage):
                with st.chat_message("user"):
                    st.markdown(message.content)
            elif isinstance(message, AIMessage):
                with st.chat_message("assistant"):
                    st.markdown(message.content)

    # Chat input at the bottom of the left column
    if prompt := st.chat_input("How can I help you with your Spotify data?", disabled=not can_chat):
        # Add user message to history
        st.session_state.messages.append(HumanMessage(content=prompt))
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        # Invoke agent
        with st.spinner("🔍 Agent is thinking... (Accessing data on first query)"):
            try:
                # Compile and cache the graph in session state
                if "agent_app" not in st.session_state:
                    st.session_state["agent_app"] = build_app()
                
                app = st.session_state["agent_app"]
                
                # Configuration for the graph (thread_id for state management)
                config = {"configurable": {"thread_id": "streamlit_session"}}
                
                # Run the agent with the current prompt and history
                final_state = app.invoke(
                    {
                        "input": prompt,
                        "messages": st.session_state.messages
                    },
                    config=config
                )
                
                # Extract the response
                response_text = final_state.get("final_response")
                if not response_text:
                    response_text = "I processed your request but didn't generate a final text response."
            
            except Exception as e:
                response_text = f"An error occurred: {str(e)}"
            
            # Add assistant message to history and display
            st.session_state.messages.append(AIMessage(content=response_text))
            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(response_text)
