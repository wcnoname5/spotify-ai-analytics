"""Shared logging setup for scripts — console + file handler at logs/pipeline.log."""
import logging
import os

from dotenv import load_dotenv
load_dotenv()

import sys
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_FMT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"


def setup_logging(verbose: bool = False, log_name: str = "pipeline") -> None:

      # allow overriding log level with env var, else default to DEBUG if verbose else INFO
    level = logging.DEBUG if verbose else os.environ.get("LOG_LEVEL", default="INFO").upper()
    fmt = logging.Formatter(_FMT)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # let handlers decide their own floor

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    _LOG_DIR.mkdir(exist_ok=True)
    fh = logging.FileHandler(_LOG_DIR / f"{log_name}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)
