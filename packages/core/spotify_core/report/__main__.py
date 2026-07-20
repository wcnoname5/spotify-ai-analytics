"""Process entry: uv run python -m spotify_core.report --style roast --start ... --end ...

Contract (spawned by the Tauri Rust backend): report markdown on stdout only,
diagnostics on stderr, non-zero exit on failure.
"""
import argparse
import sys


def main() -> int:
    p = argparse.ArgumentParser(prog="spotify_core.report")
    p.add_argument("--style", required=True, choices=["listening_review", "roast"])
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--period-type", default="weekly", choices=["weekly", "monthly", "quarterly"])
    p.add_argument("--db", default=None, help="history.db path (default: settings)")
    p.add_argument("--provider", default="google")
    p.add_argument("--model", default=None, help="default: settings.gemini_model")
    p.add_argument("--no-save", action="store_true", help="skip local save + push (throwaway run)")
    args = p.parse_args()

    from spotify_core.config import settings
    from spotify_core.report.graph import generate_report
    from spotify_core.report.models import build_chat_model

    model = build_chat_model(args.provider, args.model or settings.gemini_model)
    result = generate_report(
        style=args.style,
        start_date=args.start,
        end_date=args.end,
        db_path=str(args.db or settings.history_db_path),
        model=model,
        period_type=args.period_type,
    )
    print(result.text)

    if not args.no_save:
        import os
        import uuid
        from datetime import datetime, timezone

        from spotify_core.db.report_store import push_unsynced, save_report_local
        from spotify_core.db.worker_client import WorkerClient

        db_path = str(args.db or settings.history_db_path)
        save_report_local(db_path, {
            "id": str(uuid.uuid4()),
            "style": args.style,
            "period_type": args.period_type,
            "start_date": args.start,
            "end_date": args.end,
            "provider": args.provider,
            "model": args.model or settings.gemini_model,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "revision_count": result.revision_count,
            "report_text": result.text,
        })
        worker_url = os.environ.get("WORKER_URL")
        worker_token = os.environ.get("WORKER_AUTH_TOKEN")
        if worker_url and worker_token:
            try:
                with WorkerClient(worker_url, worker_token) as worker:
                    push_unsynced(db_path, worker)
            except Exception as exc:  # fail-soft: row stays synced=0, retried next sync
                print(f"warning: report push failed ({exc})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
