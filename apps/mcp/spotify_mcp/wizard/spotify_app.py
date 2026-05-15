"""Wizard step: probe OAuth port, then walk the user through Spotify app registration."""
import socket
import webbrowser
from contextlib import closing

from rich.console import Console
from rich.panel import Panel

OAUTH_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{OAUTH_PORT}/callback"
DASHBOARD_URL = "https://developer.spotify.com/dashboard"


class PortInUseError(RuntimeError):
    """Raised when the OAuth port is already bound."""


def port_available(port: int) -> bool:
    """True if 127.0.0.1:port can be bound right now."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _open_browser(url: str) -> None:
    webbrowser.open(url)


_CHECKLIST = """
[bold]In the Spotify dashboard:[/bold]
  1. Click [bold]Create app[/bold]
  2. Enter any name and description
  3. [bold]Redirect URI:[/bold] paste this exact value, then click [bold]Add[/bold]:
       [cyan]{redirect_uri}[/cyan]
  4. API/SDK: tick [bold]Web API[/bold]
  5. Accept the Terms of Service, click [bold]Save[/bold]
  6. Open the app's [bold]Settings[/bold] page and copy the [bold]Client ID[/bold]
"""


def run_step(console: Console, port: int = OAUTH_PORT) -> None:
    """Probe the OAuth port and print the dashboard checklist.

    Raises:
        PortInUseError: if the port is already bound.
    """
    if not port_available(port):
        raise PortInUseError(
            f"Port {port} is already in use. Free it before continuing.\n"
            f"  Common causes: another spotify-mcp setup in progress, a Docker container, "
            f"a local web server.\n"
            f"  Find what's bound: lsof -i :{port}  (Unix)  /  netstat -ano | findstr :{port}  (Windows)"
        )

    console.print(Panel.fit(
        f"Opening the Spotify Developer Dashboard at\n  [cyan]{DASHBOARD_URL}[/cyan]",
        title="Step 1 / 6: Register your Spotify app",
    ))
    _open_browser(DASHBOARD_URL)
    console.print(_CHECKLIST.format(redirect_uri=REDIRECT_URI))
