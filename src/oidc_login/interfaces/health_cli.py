"""``oidc-login-health``: exit 0 when the running app answers ``/healthz`` (the container's health check).

Liveness only: the app being up does not depend on the provider being up. ``/readyz`` adds the provider check.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    """Probe the liveness endpoint on the loopback address; print the outcome and return the exit code."""
    port = os.environ.get("APP_PORT", "3000")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            ok = response.status == 200
    except (urllib.error.URLError, OSError) as error:
        print(f"unhealthy: {error}", file=sys.stderr)
        return 1
    print("healthy" if ok else "unhealthy")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
