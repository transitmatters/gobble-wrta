import json
import urllib.request
from typing import Any

BASE_URL = "https://swiv.wrta.cadavl.com/SWIV/WRTA/proxy/restWS"


def get_json(path: str) -> dict[str, Any]:
    """Fetches JSON from the vendor's API at the given path, returning it as a dict."""
    with urllib.request.urlopen(BASE_URL + path) as response:
        return json.loads(response.read())
