"""Tests for SpotifyPlaybackTools (Stage 5). All SpotifyClient calls are mocked."""
import pytest
from unittest.mock import MagicMock, patch
from spotify_core.agent.playback_tools import SpotifyPlaybackTools


def _make_tools(client=None):
    if client is None:
        client = MagicMock()
    return SpotifyPlaybackTools(
        client=client,
        db_path="data/history.db",
        tokens_db_path="data/tokens.db",
        user_id="test_user",
        client_id="test_client_id",
        fernet_key=b"fake_key",
    )


class TestGetNowPlaying:
    def test_returns_track_info(self):
        client = MagicMock()
        client.get_currently_playing.return_value = {
            "is_playing": True,
            "progress_ms": 60000,
            "item": {
                "name": "Bohemian Rhapsody",
                "uri": "spotify:track:abc",
                "artists": [{"name": "Queen"}],
                "album": {"name": "A Night at the Opera"},
            },
        }
        tools = _make_tools(client)
        result = tools.get_now_playing()
        assert result["track"] == "Bohemian Rhapsody"
        assert result["artist"] == "Queen"
        assert result["is_playing"] is True

    def test_nothing_playing(self):
        client = MagicMock()
        client.get_currently_playing.return_value = None
        tools = _make_tools(client)
        result = tools.get_now_playing()
        assert result == {"status": "nothing_playing"}

    def test_api_error_returns_error_dict(self):
        client = MagicMock()
        client.get_currently_playing.side_effect = RuntimeError("network error")
        tools = _make_tools(client)
        result = tools.get_now_playing()
        assert "error" in result


class TestPlayTrack:
    def test_success(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.play_track("spotify:track:abc")
        client.play.assert_called_once_with(uris=["spotify:track:abc"])
        assert result == {"status": "playing", "uri": "spotify:track:abc"}

    def test_premium_required(self):
        client = MagicMock()
        client.play.side_effect = Exception("403 Forbidden PREMIUM_REQUIRED")
        tools = _make_tools(client)
        result = tools.play_track("spotify:track:abc")
        assert "error" in result or result.get("error")


class TestPlayPlaylistOrAlbum:
    def test_plays_playlist(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.play_playlist_or_album("spotify:playlist:abc")
        client.play.assert_called_once_with(context_uri="spotify:playlist:abc")
        assert result == {"status": "playing", "context_uri": "spotify:playlist:abc"}

    def test_plays_album(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.play_playlist_or_album("spotify:album:xyz")
        client.play.assert_called_once_with(context_uri="spotify:album:xyz")
        assert result == {"status": "playing", "context_uri": "spotify:album:xyz"}

    def test_premium_required(self):
        client = MagicMock()
        client.play.side_effect = Exception("403 Forbidden PREMIUM_REQUIRED")
        tools = _make_tools(client)
        result = tools.play_playlist_or_album("spotify:playlist:abc")
        assert "error" in result


class TestSearchItem:
    def _make_track(self, name="Track A", artist="Artist A", album="Album A", uri="spotify:track:t1"):
        return {
            "name": name,
            "uri": uri,
            "artists": [{"name": artist}],
            "album": {"name": album},
        }

    def _make_artist(self, name="Artist A", uri="spotify:artist:a1"):
        return {"name": name, "uri": uri}

    def _make_album(self, name="Album A", artist="Artist A", uri="spotify:album:al1"):
        return {"name": name, "uri": uri, "artists": [{"name": artist}]}

    def _make_playlist(self, name="Playlist A", owner="user1", uri="spotify:playlist:p1"):
        return {"name": name, "uri": uri, "owner": {"display_name": owner}}

    def test_search_tracks_returns_formatted_results(self):
        client = MagicMock()
        client.search.return_value = {
            "tracks": {"items": [self._make_track()]},
        }
        tools = _make_tools(client)
        result = tools.search_item("Track A")
        client.search.assert_called_once_with("Track A", types=["track"], limit=5)
        assert "tracks" in result
        assert result["tracks"][0] == {
            "name": "Track A",
            "artist": "Artist A",
            "album": "Album A",
            "uri": "spotify:track:t1",
        }

    def test_search_albums_returns_formatted_results(self):
        client = MagicMock()
        client.search.return_value = {
            "albums": {"items": [self._make_album()]},
        }
        tools = _make_tools(client)
        result = tools.search_item("Abbey Road", types=["album"])
        client.search.assert_called_once_with("Abbey Road", types=["album"], limit=5)
        assert "albums" in result
        assert result["albums"][0] == {
            "name": "Album A",
            "artist": "Artist A",
            "uri": "spotify:album:al1",
        }

    def test_search_artists_returns_formatted_results(self):
        client = MagicMock()
        client.search.return_value = {
            "artists": {"items": [self._make_artist()]},
        }
        tools = _make_tools(client)
        result = tools.search_item("Artist A", types=["artist"])
        assert "artists" in result
        assert result["artists"][0] == {"name": "Artist A", "uri": "spotify:artist:a1"}

    def test_search_playlists_returns_formatted_results(self):
        client = MagicMock()
        client.search.return_value = {
            "playlists": {"items": [self._make_playlist()]},
        }
        tools = _make_tools(client)
        result = tools.search_item("chill vibes", types=["playlist"])
        assert "playlists" in result
        assert result["playlists"][0] == {
            "name": "Playlist A",
            "owner": "user1",
            "uri": "spotify:playlist:p1",
        }

    def test_search_multi_type_returns_all_types(self):
        client = MagicMock()
        client.search.return_value = {
            "tracks": {"items": [self._make_track()]},
            "artists": {"items": [self._make_artist()]},
        }
        tools = _make_tools(client)
        result = tools.search_item("queen", types=["track", "artist"])
        client.search.assert_called_once_with("queen", types=["track", "artist"], limit=5)
        assert "tracks" in result
        assert "artists" in result

    def test_search_custom_limit_is_passed_through(self):
        client = MagicMock()
        client.search.return_value = {"tracks": {"items": []}}
        tools = _make_tools(client)
        tools.search_item("anything", limit=10)
        client.search.assert_called_once_with("anything", types=["track"], limit=10)

    def test_search_api_error_returns_error_dict(self):
        client = MagicMock()
        client.search.side_effect = RuntimeError("network error")
        tools = _make_tools(client)
        result = tools.search_item("anything")
        assert "error" in result


class TestPause:
    def test_success(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.pause()
        client.pause.assert_called_once()
        assert result == {"status": "paused"}

    def test_error_returns_dict(self):
        client = MagicMock()
        client.pause.side_effect = Exception("something failed")
        tools = _make_tools(client)
        result = tools.pause()
        assert "error" in result


class TestSkip:
    def test_success(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.skip()
        client.skip_to_next.assert_called_once()
        assert result == {"status": "skipped"}


class TestSetVolume:
    def test_success(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.set_volume(75)
        client.set_volume.assert_called_once_with(75)
        assert result == {"status": "volume_set", "volume_percent": 75}

    def test_clamps_above_100(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.set_volume(150)
        client.set_volume.assert_called_once_with(100)
        assert result["volume_percent"] == 100

    def test_clamps_below_0(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.set_volume(-10)
        client.set_volume.assert_called_once_with(0)
        assert result["volume_percent"] == 0


class TestAddToQueue:
    def test_success(self):
        client = MagicMock()
        tools = _make_tools(client)
        result = tools.add_to_queue("spotify:track:xyz")
        client.add_to_queue.assert_called_once_with("spotify:track:xyz")
        assert result == {"status": "queued", "uri": "spotify:track:xyz"}


class TestCreatePlaylist:
    def test_creates_and_adds_tracks(self):
        client = MagicMock()
        client.create_playlist.return_value = {
            "id": "playlist_123",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist_123"},
        }
        tools = _make_tools(client)
        result = tools.create_playlist("My Playlist", ["spotify:track:a", "spotify:track:b"])
        client.create_playlist.assert_called_once_with(
            "test_user", "My Playlist", public=False, description=""
        )
        client.add_tracks_to_playlist.assert_called_once_with(
            "playlist_123", ["spotify:track:a", "spotify:track:b"]
        )
        assert result["playlist_id"] == "playlist_123"
        assert result["track_count"] == 2


class TestSyncRecentHistory:
    def test_delegates_to_sync_api_to_db(self):
        with patch("spotify_core.agent.playback_tools.sync_api_to_db") as mock_sync:
            mock_sync.return_value = {"inserted": 10, "cursor_ms": 1700000000000}
            tools = _make_tools()
            result = tools.sync_recent_history()

        mock_sync.assert_called_once_with(
            db_path="data/history.db",
            tokens_db_path="data/tokens.db",
            user_id="test_user",
            client_id="test_client_id",
            fernet_key=b"fake_key",
        )
        assert result == {"inserted": 10, "cursor_ms": 1700000000000}

    def test_error_returns_dict(self):
        with patch("spotify_core.agent.playback_tools.sync_api_to_db") as mock_sync:
            mock_sync.side_effect = RuntimeError("No token found")
            tools = _make_tools()
            result = tools.sync_recent_history()
        assert "error" in result


class TestGetTools:
    def test_returns_list_of_tools(self):
        tools = _make_tools()
        tool_list = tools.get_tools()
        assert len(tool_list) == 8
        names = [t.name for t in tool_list]
        assert "get_now_playing" in names
        assert "sync_recent_history" in names
        assert "create_playlist" in names
