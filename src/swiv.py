import json
import urllib.request
from typing import Any

BASE_URL = "https://swiv.wrta.cadavl.com/SWIV/WRTA/proxy/restWS"
TIMEOUT_SECONDS = 10


def get_json(path: str) -> dict[str, Any]:
    """Fetches JSON from the vendor's API at the given path, returning it as a dict.

    Raises on non-2xx responses, connection failures, or timeout -- callers are responsible
    for deciding how to handle a temporarily unavailable vendor API (e.g. retrying on the
    next poll cycle rather than crashing).
    """
    with urllib.request.urlopen(BASE_URL + path, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read())
