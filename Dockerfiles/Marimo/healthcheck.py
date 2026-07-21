#!/opt/marimo/.venv/bin/python
from urllib.error import URLError
from urllib.request import urlopen


try:
    with urlopen("http://127.0.0.1:8080/health", timeout=3) as response:
        healthy = response.status == 200
except (OSError, URLError):
    healthy = False

raise SystemExit(0 if healthy else 1)
