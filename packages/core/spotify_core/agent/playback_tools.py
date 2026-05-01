"""LangChain-wrapped playback tools for agent integration."""
from langchain_core.tools import tool

from ..spotify_utils.playback import SpotifyPlaybackTools


class AgentPlaybackTools(SpotifyPlaybackTools):
    """SpotifyPlaybackTools with LangChain tool wrapping for agent integration."""

    def get_tools(self) -> list:
        """Return all playback/sync methods as LangChain tools."""
        return [
            tool(self.get_now_playing),
            tool(self.play_track),
            tool(self.pause),
            tool(self.skip),
            tool(self.set_volume),
            tool(self.add_to_queue),
            tool(self.create_playlist),
            tool(self.sync_recent_history),
        ]
