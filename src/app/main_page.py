import streamlit as st
import zipfile
import tempfile
import pathlib
import shutil
from dataloader import SpotifyDataLoader
from app.chatbot_page import render_chatbot
from app.dashboard import render_dashboard
from utils.agent_utils import (
    inject_shared_loader, 
    reset_resources, 
    resolve_api_key, 
    resolve_data_loader,
    is_cloud
)
from utils.loggings import setup_logging
from config.settings import settings

# Configure logging
setup_logging()

# Set page configuration
st.set_page_config(layout="wide", page_title="Spotify AI Analytics", page_icon="🎵")

def handle_zip_upload(uploaded_file):
    """Extract uploaded zip and return a loader pointing to the temp directory."""
    # Create a persistent temp directory in session state if it doesn't exist
    if "temp_dir" in st.session_state:
        # Cleanup old directory
        shutil.rmtree(st.session_state["temp_dir"], ignore_errors=True)
    
    tmp_path = tempfile.mkdtemp()
    st.session_state["temp_dir"] = tmp_path
    
    with zipfile.ZipFile(uploaded_file, "r") as zip_ref:
        zip_ref.extractall(tmp_path)
    
    return SpotifyDataLoader(pathlib.Path(tmp_path))

def main():
    st.title("Spotify AI Analytics Agent")

    # Resolve Data
    loader, data_source = resolve_data_loader()
    
    # Inject loader into agent utilities
    if loader:
        inject_shared_loader(loader)
    
    # Check if we have data records
    has_data = loader is not None and not loader.df.is_empty()

    if "model_provider" not in st.session_state:
        st.session_state["model_provider"] = "Gemini" if settings.use_gemini else "OpenAI"

    # ========== SIDEBAR ==========
    with st.sidebar:        
        # Navigation
        st.header("Navigation")
        page = st.radio(
            "Select View",
            ["Chatbot", "Dashboard"],
            horizontal=True,
            index=0,
            key="nav_radio"
        )

        st.divider()
        st.header("Settings")
        st.markdown("Configure AI model and data options first to enable the app.")
        # Model Configuration
        st.subheader("AI Configuration")
        provider = st.radio(
            "Select Model Provider",
            ["Gemini", "OpenAI"],

            index=0 if st.session_state["model_provider"] == "Gemini" else 1,
            help="Choose which AI agent to use."
        )
        
        if provider != st.session_state["model_provider"]:
            st.session_state["model_provider"] = provider
            reset_resources()
            st.rerun()

        # API Key Resolution and UI
        _, key_source = resolve_api_key(provider)
        session_key_name = "gemini_api_key" if provider == "Gemini" else "openai_api_key"
        input_key_name = f"input_{session_key_name}"
        
        # Display current status
        if key_source == "session":
            st.success(f"{provider} API key: Using session override")
            if st.button("Clear Custom Key"):
                if session_key_name in st.session_state:
                    del st.session_state[session_key_name]
                if input_key_name in st.session_state:
                    st.session_state[input_key_name] = ""
                reset_resources()
                st.rerun()
        elif key_source == "env":
            st.info(f"{provider} API key: Using .env configuration")
        else:
            st.warning(f"{provider} API key: Not configured")
        
        # Always allow override
        # We don't use the return value directly to avoid instant rerun on every interaction
        # Instead we check if the value in session state changed
        st.text_input(
            f"{provider} API Key Override",
            type="password",
            help=f"Enter a {provider} API key to override the current configuration.",
            key=input_key_name
        )
        
        current_input = st.session_state.get(input_key_name, "")
        if current_input and current_input != st.session_state.get(session_key_name):
            st.session_state[session_key_name] = current_input
            reset_resources()
            st.rerun()

        st.divider()

        # Data Management
        st.subheader("Data Management")
        if data_source != "none":
            st.info(f"Using data from: {data_source}")
        
        uploaded_file = st.file_uploader("Upload Spotify History (.zip)", type="zip")
        
        if uploaded_file is not None:
            if st.button("Process Uploaded Data"):
                with st.spinner("Extracting and processing data..."):
                    try:
                        # Shared loader is injected here
                        st.session_state["loader"] = handle_zip_upload(uploaded_file)
                        inject_shared_loader(st.session_state["loader"])
                        
                        # Reset Chat History for new data
                        if "messages" in st.session_state:
                            st.session_state.messages = []
                        
                        st.success("Data loaded successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error processing zip: {e}")
        st.divider()
        if st.button("Reset Session / Clear Data", type="primary"):
            # Clear all overrides
            for key in ["loader", "gemini_api_key", "openai_api_key", "messages"]:
                if key in st.session_state:
                    del st.session_state[key]
            if "temp_dir" in st.session_state:
                shutil.rmtree(st.session_state["temp_dir"], ignore_errors=True)
                del st.session_state["temp_dir"]
            reset_resources()
            st.rerun()

    
    # Main Content Area
    if not has_data:
        st.info("👋 Welcome! Please upload your Spotify data export (.zip) in the sidebar to get started.")
        st.markdown("""
        ### How to get your data:
        1. Go to your [Spotify Account Privacy Settings](https://www.spotify.com/account/privacy/).
        2. Request your **Extended streaming history**.
        3. Wait for Spotify to email you the download link (usually takes a few days).
        4. Upload the resulting `.zip` file here.
        """)
        return

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
