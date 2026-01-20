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
    validate_api_key,
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
        # Quick Validation of file names
        file_list = zip_ref.namelist()
        valid_files = [f for f in file_list if "Streaming_History_Audio_" in f and f.endswith(".json")]
        
        if not valid_files:
            # Clean up the directory since we won't use it
            shutil.rmtree(tmp_path, ignore_errors=True)
            del st.session_state["temp_dir"]
            raise ValueError(
                "No valid Spotify history files (e.g., 'Streaming_History_Audio_*.json') found in the ZIP. "
                "Did you request the **Extended streaming history**?"
            )
            
        zip_ref.extractall(tmp_path)
    
    return SpotifyDataLoader(pathlib.Path(tmp_path))

def main():
    st.title("Spotify AI Analytics Agent")

    # Resolve Data
    loader, data_source = resolve_data_loader()
    
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
        api_key, key_source = resolve_api_key(provider)
        session_key_name = "gemini_api_key" if provider == "Gemini" else "openai_api_key"
        input_key_name = f"input_{session_key_name}"
        
        # Validation
        validation_status = "unchecked"
        if api_key:
            validation_status = validate_api_key(provider, api_key)

        # Display current status
        if key_source == "session":
            if validation_status == "valid":
                st.success(f"✅ {provider} API key: Active")
            elif validation_status == "invalid":
                st.error(f"❌ {provider} API key: Invalid key")
            elif validation_status == "network_error":
                st.warning(f"⚠️ {provider} API key: Network issue")
                if st.button("Retry Validation"):
                    # Clearing auth cache from session state
                    for k in list(st.session_state.keys()):
                        if k.startswith("auth_cache_"):
                            del st.session_state[k]
                    reset_resources()
                    st.rerun()

            if st.button("Clear Custom Key"):
                if session_key_name in st.session_state:
                    del st.session_state[session_key_name]
                if input_key_name in st.session_state:
                    st.session_state[input_key_name] = ""
                reset_resources()
                st.rerun()
        # read local .env key
        elif key_source == "env":
            if validation_status == "valid":
                st.success(f"✅ {provider} API key: Using .env")
            elif validation_status == "invalid":
                st.error(f"❌ {provider} API key: .env key invalid")
            elif validation_status == "network_error":
                st.warning(f"⚠️ {provider} API key: .env connection issue")
                if st.button("Retry Validation"):
                    for k in list(st.session_state.keys()):
                        if k.startswith("auth_cache_"):
                            del st.session_state[k]
                    reset_resources()
                    st.rerun()
        else:
            st.warning(f"{provider} API key: Not configured")
        
        
        if st.session_state.get(input_key_name):
            help_text = f"Enter a {provider} API key to set the configuration."
        else:
            help_text = f"Enter a {provider} API key to override the current configuration."
        # Flied to enter API key
        st.text_input(
            f"{provider} API Key",
            type="password",
            help=help_text,
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
        if data_source != "none" and has_data:
            st.success(f"✅ Data Ready: {data_source}")
        elif data_source != "none" and not has_data:
            st.warning("⚠️ Data source found but contains no records.")
        else:
            st.info("ℹ️ No data loaded. Please upload your history.")
        
        uploaded_file = st.file_uploader("Upload Spotify History (.zip)", type="zip")

        if uploaded_file is not None:
            if st.button("Process Uploaded Data"):
                with st.spinner("Extracting and processing data..."):
                    try:
                        # Shared loader is injected here
                        loader_obj = handle_zip_upload(uploaded_file)
                        st.session_state["loader"] = loader_obj
                        inject_shared_loader(loader_obj)
                        
                        # Reset Chat History for new data
                        if "messages" in st.session_state:
                            st.session_state.messages = []
                        
                        st.success("Data loaded successfully!")
                        st.rerun()
                    except ValueError as ve:
                        st.error(f"{ve}")
                        st.markdown("[How to get the right data?](https://support.spotify.com/us/article/understanding-your-data/)")
                    except Exception as e:
                        st.error(f"Error processing zip: {e}")
        st.divider()
        if st.button("Reset Session / Clear Data", type="primary"):
            # Clear all overrides
            for key in ["loader", "gemini_api_key", "openai_api_key", "messages", "input_gemini_api_key", "input_openai_api_key"]:
                if key in st.session_state:
                    del st.session_state[key]
            
            if "temp_dir" in st.session_state:
                shutil.rmtree(st.session_state["temp_dir"], ignore_errors=True)
                del st.session_state["temp_dir"]
                
            reset_resources()
            st.success("Session reset successfully.")
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
