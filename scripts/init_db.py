"""Initialize data/history.db and optionally trigger OAuth flow."""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spotify_core.db.pipeline import init_history_db


def main():
    parser = argparse.ArgumentParser(description="Initialize the Spotify history database")
    parser.add_argument(
        "--db", default="data/history.db",
        help="Path to history.db (default: data/history.db)"
    )
    parser.add_argument(
        "--auth", action="store_true",
        help="After DB init, run the Spotify OAuth PKCE flow to store tokens"
    )
    parser.add_argument(
        "--tokens-db", default="data/tokens.db",
        help="Path to tokens.db (default: data/tokens.db, used with --auth)"
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--user-id",
        help="Your Spotify user ID (required with --auth, e.g. your Spotify username)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info("Initializing history DB at %s", args.db)
    init_history_db(args.db)
    logger.info("Done. DB ready at %s", args.db)

    if args.auth:
        from spotify_core.spotify_client.auth import run_pkce_flow
        from spotify_core.spotify_client.token_store import save_tokens

        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")
        if not client_id:
            logger.error("SPOTIFY_CLIENT_ID not set in environment")
            sys.exit(1)
        if not fernet_key_str:
            logger.error(
                "TOKEN_ENCRYPT_KEY not set — generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
            sys.exit(1)

        fernet_key = fernet_key_str.encode()
        if not args.user_id:
            logger.error("--user-id is required when using --auth (your Spotify username)")
            sys.exit(1)
        logger.info("Starting OAuth PKCE flow — your browser will open")
        token_data = run_pkce_flow(client_id=client_id)
        user_id = args.user_id
        save_tokens(args.tokens_db, user_id, token_data, fernet_key)
        logger.info("Tokens saved for user_id='%s' in %s", user_id, args.tokens_db)


if __name__ == "__main__":
    main()
