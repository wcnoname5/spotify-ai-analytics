import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from spotify_agent.graph import build_app

def render_chatbot():
    st.header("Spotify Data Chatbot")
    # Create two columns (Left for Chat, Right for Visualizations)
    col_chat, col_viz = st.columns([1, 1])

    # Initialize session state for messages if not exists
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Left column: Chatbot interface
    with col_chat:
        st.subheader("Chat Interface")
        
        # Display chat history in a scrollable container
        chat_container = st.container(height=600)
        with chat_container:
            for message in st.session_state.messages:
                if isinstance(message, HumanMessage):
                    with st.chat_message("user"):
                        st.markdown(message.content)
                elif isinstance(message, AIMessage):
                    with st.chat_message("assistant"):
                        st.markdown(message.content)

        # Chat input at the bottom of the left column
        if prompt := st.chat_input("How can I help you with your Spotify data?"):
            # Add user message to history
            st.session_state.messages.append(HumanMessage(content=prompt))
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt)

            # Invoke agent
            with st.spinner("Agent is thinking..."):
                try:
                    # Compile the graph
                    app = build_app()
                    
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

    # Right column: Empty space
    with col_viz:
        st.subheader("Analysis Results")
        st.write("Results and visualizations will be displayed here in the future.")
        # Currently empty as requested
        st.empty()
