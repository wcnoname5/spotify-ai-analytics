import streamlit as st
import os
from dotenv import load_dotenv
from app.chatbot_page import render_chatbot
from app.dashboard import render_dashboard
from utils.loggings import setup_logging

# Configure logging
setup_logging()
load_dotenv()

# Set page configuration
st.set_page_config(layout="wide", page_title="Spotify AI Analytics", page_icon="🎵")

def main():
    st.title("Spotify AI Analytics Agent")

    # Create Tabs
    tab_chatbot, tab_dashboard = st.tabs(["Chatbot", "Dashboard"])

    # First tab: Chatbot interface
    with tab_chatbot:
        render_chatbot()
    
    # Second tab: Visual Dashboard
    with tab_dashboard:
        render_dashboard()

if __name__ == "__main__":
    main()
