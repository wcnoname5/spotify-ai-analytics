import streamlit as st
from dataloader import SpotifyDataLoader
from app.chatbot_page import render_chatbot
from app.dashboard import render_dashboard
from utils.agent_utils import inject_shared_loader
from utils.loggings import setup_logging
from config.settings import settings

# Configure logging
setup_logging()

# Set page configuration
st.set_page_config(layout="wide", page_title="Spotify AI Analytics", page_icon="🎵")

# return loader as a global instance (cached resource)
@st.cache_resource
def get_loader():
    """
    Cached loader that returns a singleton instance across page reruns.
    Data is loaded lazily on first access.
    """
    # Use path from centralized settings
    loader = SpotifyDataLoader(settings.spotify_data_path)
    return loader

def main():
    st.title("Spotify AI Analytics Agent")

    # ========== SINGLE SHARED LOADER INITIALIZATION ==========
    # The loader is cached globally via @st.cache_resource in get_loader()
    # This ensures it's a true singleton across all page reruns and tabs.
    with st.spinner("🎵 Loading Spotify history data..."):
        loader = get_loader()
    
    # Inject the cached loader into the agent's utilities
    # This ensures the chatbot uses the same data instance as the dashboard
    inject_shared_loader(loader)

    # ========== CONDITIONAL RENDERING (instead of st.tabs) ==========
    # Using a sidebar to avoid executing Dashboard code until explicitly selected
    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "Select View",
            ["Chatbot", "Dashboard"],
            index=0,
            key="nav_radio"
        )

    # Render the selected page
    if page == "Chatbot":
        st.divider()
        render_chatbot()
    elif page == "Dashboard":
        st.divider()
        # inject global loader instance into dashboard
        render_dashboard(loader)


if __name__ == "__main__":
    main()
