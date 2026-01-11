'''
Pydantic model for a Spotify track in DataLoader
'''
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from typing import Optional, Literal, List

# --- Constants for Data Consistency ---
# These lists serve as the single source of truth for both Pydantic validation
# and Polars categorical/Enum types.
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
REASON_START = [
    "clickrow", "trackdone", "appload", "fwdbtn", "backbtn",
    "remote", "playbtn", "unknown", "switched-to-audio", "switched-to-video"
]
REASON_END = [
    "trackerror", "trackdone", "endplay", "logout", "fwdbtn",
    "backbtn", "unexpected-exit", "remote", "unexpected-exit-while-paused",
    "unknown"
]

class JsonTrackRecord(BaseModel):
    '''
    A model representing the raw JSON structure of a Spotify track record
    as found in the Spotify listening history data.
    make sure the input JSON structure matches the following example:
    '''
    ts: str # ISO 8601 format
    platform: Optional[str] # e.g., "Android"
    ms_played: int
    conn_country: Optional[str] # country code, e.g.,"TW" 
    ip_addr: Optional[str]
    master_metadata_track_name: str
    master_metadata_album_artist_name: str
    master_metadata_album_album_name: str
    spotify_track_uri: str # required, format: "spotify:track:6KE0cMC0Sa9NJMt8dbmAp8"
    # ==== audiobook/podcast related fields ====
    episode_name: Optional[str] = None
    episode_show_name: Optional[str] = None
    spotify_episode_uri: Optional[str] = None
    audiobook_title: Optional[str] = None
    audiobook_uri: Optional[str] = None
    audiobook_chapter_uri: Optional[str] = None
    audiobook_chapter_title: Optional[str] = None
    # Additional fields tracking playing behavior
    reason_start: Literal[*REASON_START]
    reason_end: Literal[*REASON_END]
    shuffle: bool
    skipped: bool
    offline: bool
    offline_timestamp: Optional[int] = None # not sure what this field does
    incognito_mode: Optional[bool] = None


class Track(BaseModel):
    '''
    A model representing a Spotify track in DataLoader
    '''
    timestamp: datetime # parsed datetime from (Use Taipei timezone) in ISO format
    ts: str # rwar string timestamp from JSON
    ms_played: timedelta # duration format
    track: str
    artist: str
    album: str
    track_uri: str
    conn_country: str
    platform: str
    reason_start: str
    reason_end: str
    shuffle: bool
    skipped: bool
    year: int
    month: Literal[*MONTHS]
    weekday: Literal[*WEEKDAYS]
    hour: int
    date: date # yyyy-mm-dd date format