'''
Pydantic model for a Spotify track in DataLoader
'''
import pydantic
from datetime import datetime, date, timedelta


class Track(pydantic.BaseModel):
    '''
    A model representing a Spotify track in DataLoader
    '''
    timestamp: datetime
    ts: str
    ms_played: timedelta
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
    month: str # TODO: specify it is '%b' Jan, Feb...
    weekday: str #  TODO: specify it is '%a' Mon, Tue, ...
    hour: int
    date: date
