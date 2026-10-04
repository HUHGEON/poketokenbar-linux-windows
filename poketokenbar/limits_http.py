"""Small injectable JSON transport for official quota requests."""

import json
import urllib.error
import urllib.request

from .limits import HTTPStatusError, LimitsError, RateLimitedError, retry_after_seconds


def request_json(request: urllib.request.Request, timeout: float = 15):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitedError(retry_after_seconds(exc.headers)) from exc
        raise HTTPStatusError(exc.code) from exc
    except (OSError, ValueError) as exc:
        # Network exception strings may include URLs; never include request headers or bodies.
        raise LimitsError("quota request failed") from exc
