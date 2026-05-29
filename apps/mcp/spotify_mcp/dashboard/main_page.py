"""Streamlit entry point: renders the analytics dashboard (viz + AI report)."""
import streamlit as st

from spotify_core.logging import setup_logging

from spotify_mcp.dashboard.views import render_dashboard

setup_logging()
st.set_page_config(layout="wide", page_title="Spotify Analytics", page_icon="🎵")


def main() -> None:
    st.title("Spotify Analytics")
    render_dashboard()


if __name__ == "__main__":
    main()
