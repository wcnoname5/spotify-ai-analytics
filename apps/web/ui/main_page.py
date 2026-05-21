"""Streamlit entry point: navigation shell for the dashboard and chat pages."""
import streamlit as st

from spotify_core.config import settings
from spotify_core.logging import setup_logging

from chatbot_page import render_chatbot
from dashboard import render_dashboard

setup_logging()
st.set_page_config(layout="wide", page_title="Spotify Analytics", page_icon="🎵")


def main() -> None:
    st.title("Spotify Analytics")

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("View", ["Dashboard", "Chat"], key="nav_radio")
        st.divider()
        st.caption(f"Database: {settings.history_db_path}")

    if page == "Dashboard":
        render_dashboard()
    else:
        render_chatbot()


if __name__ == "__main__":
    main()
