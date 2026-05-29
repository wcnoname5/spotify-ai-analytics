"""Streamlit entry point: renders the analytics dashboard (viz + AI report)."""
import streamlit as st
from dotenv import load_dotenv

from spotify_core import paths
from spotify_core.logging import setup_logging

from spotify_mcp.dashboard.views import render_dashboard

# Bridge the platform .env into os.environ so env-based SDKs (e.g. Langfuse) see
# their credentials. Settings reads the file directly, but third-party SDKs only
# read os.environ. Mirrors apps/mcp/server.py.
load_dotenv(paths.env_file())

setup_logging()
st.set_page_config(layout="wide", page_title="Spotify Analytics", page_icon="🎵")


def main() -> None:
    st.title("Spotify Analytics")
    render_dashboard()


if __name__ == "__main__":
    main()
