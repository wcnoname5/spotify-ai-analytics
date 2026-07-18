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
    p.add_argument("--period-type", default="custom", choices=["weekly", "monthly", "custom"])
    p.add_argument("--db", default=None, help="history.db path (default: settings)")
    p.add_argument("--provider", default="google")
    p.add_argument("--model", default=None, help="default: settings.gemini_model")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
