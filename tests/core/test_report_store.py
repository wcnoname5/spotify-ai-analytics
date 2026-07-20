import httpx

from spotify_core.db.report_store import (
    get_report, list_reports, pull_reports, push_unsynced, save_report_local,
)
from spotify_core.db.worker_client import WorkerClient


def _row(i="00000000-0000-4000-8000-000000000001", gen="2026-07-20T10:00:00Z"):
    return {
        "id": i, "style": "roast", "period_type": "weekly",
        "start_date": "2026-07-06", "end_date": "2026-07-12",
        "provider": "google", "model": "gemini-3.5-flash",
        "generated_at": gen, "revision_count": 1, "report_text": "# hi",
    }


def _worker(handler):
    return WorkerClient("https://w.example", "tok",
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_save_push_pull_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    save_report_local(db, _row())
    save_report_local(db, _row())  # idempotent
    assert len(list_reports(db)) == 1
    assert get_report(db, _row()["id"])["synced"] == 0

    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(200, json={"inserted": 1})
        assert request.url.params["since"] == "2026-07-20T10:00:00Z"
        remote = _row(i="00000000-0000-4000-8000-000000000002",
                      gen="2026-07-20T11:00:00Z")
        return httpx.Response(200, json={"reports": [remote]})

    worker = _worker(handler)
    assert push_unsynced(db, worker) == 1
    assert get_report(db, _row()["id"])["synced"] == 1
    assert push_unsynced(db, worker) == 0          # outbox drained
    assert pull_reports(db, worker) == 1           # cursor pull, stored synced=1
    assert len(list_reports(db)) == 2
