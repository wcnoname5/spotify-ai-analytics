"""Typed exceptions for the local SQLite analytics layer.

Kept separate from spotify_client errors because these failures are about
local history data — not OAuth tokens — so callers should react differently
(prompt the user to import history, not to re-authenticate).
"""


class HistoryDBError(Exception):
    """Base class for errors raised by the history DB layer."""


class HistoryNotInitializedError(HistoryDBError):
    """The history.db file or listening_history table is missing.

    Raised when an analytics query runs against a DB that has not been
    created/migrated yet. Recovery: run the import or sync flow.
    """
