import os 
import sys
from datetime import datetime
import logging
from config.settings import PROJECT_ROOT

def setup_logging(mode="app", log_name=None, level=logging.DEBUG):
    """
    Setup logging to file and console with UTF-8 support.
    
    Args:
        mode: "app" for normal usage, "test" for pytest runs
        log_name: Optional prefix for the log filename
        level: Logging level (default to DEBUG to catch all details)
    """
    # Ensure stdout/stderr can handle UTF-8 symbols on Windows
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            # Fallback for environments where reconfigure might fail
            pass

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    if mode == "test":
        folder = "tests"
        filename = f"test_{log_name}_{timestamp}.log" if log_name else f"test_debug_{timestamp}.log"
    else:
        folder = "app"
        filename = f"spotify_agent_debug-{timestamp}.log"
        
    log_file = PROJECT_ROOT / "logs" / folder / filename
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # We create handlers explicitly to ensure encoding is set correctly where possible
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    stream_handler = logging.StreamHandler(sys.stdout)
    # On Windows, StreamHandler might still struggle with some envs, 
    # but sys.stdout.reconfigure usually helps.

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[file_handler, stream_handler],
        force=True
    )
