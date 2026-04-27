"""Initialize data/history.db and optionally trigger OAuth flow."""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

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

        from spotify_core.db.migrations import init_tokens_db
        # Always ensure tokens table exists in the specified tokens DB
        init_tokens_db(args.tokens_db)

        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")
        if not client_id:
            logger.error("SPOTIFY_CLIENT_ID not set in environment")
            sys.exit(1)
        if not fernet_key_str:
            from cryptography.fernet import Fernet
            new_key = Fernet.generate_key().decode()
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                content = env_path.read_text()
                import re as _re
                if "TOKEN_ENCRYPT_KEY=" in content:
                    content = _re.sub(r"TOKEN_ENCRYPT_KEY=\S*", f"TOKEN_ENCRYPT_KEY={new_key}", content)
                else:
                    content += f"\nTOKEN_ENCRYPT_KEY={new_key}\n"
                env_path.write_text(content)
                logger.info("Auto-generated TOKEN_ENCRYPT_KEY and saved to %s", env_path)
            else:
                logger.warning("No .env file found — add this line to your .env: TOKEN_ENCRYPT_KEY=%s", new_key)
            fernet_key_str = new_key
            os.environ["TOKEN_ENCRYPT_KEY"] = new_key

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
