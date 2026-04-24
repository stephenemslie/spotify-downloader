"""
Fetch an anonymous Spotify access token from the web player endpoint.

This avoids the need for developer-registered client credentials.
The token is obtained the same way a browser does when visiting open.spotify.com,
so it works for any public resource (playlists, tracks, albums).

Limitations:
- Spotify blocks requests from datacenter/server IP ranges. This works from
  residential IPs and typical user machines, not cloud CI environments.
- The anonymous token expires (typically within one hour). Long download sessions
  may need a token refresh.
"""

import logging
from typing import Tuple

import requests

__all__ = ["SpotifyAnonError", "get_anonymous_token"]

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.spotify.com/get_access_token"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://open.spotify.com/",
}


class SpotifyAnonError(Exception):
    """Raised when the anonymous token cannot be obtained."""


def get_anonymous_token() -> Tuple[str, int]:
    """
    Obtain an anonymous Spotify access token from the web player endpoint.

    No Spotify developer credentials are required. Works for public playlists,
    albums, tracks, and artists.

    Returns:
        (access_token, expiry_timestamp_ms) — the bearer token and when it expires.

    Raises:
        SpotifyAnonError: if Spotify blocks the request or returns an unexpected response.
    """
    try:
        resp = requests.get(
            _TOKEN_URL,
            params={"reason": "transport", "productType": "web_player"},
            headers=_HEADERS,
            timeout=10,
        )
    except requests.RequestException as exc:
        raise SpotifyAnonError(f"Network error fetching anonymous token: {exc}") from exc

    if resp.status_code == 403:
        deny_reason = resp.headers.get("x-deny-reason", "unknown")
        raise SpotifyAnonError(
            f"Spotify blocked the anonymous token request ({deny_reason}). "
            "This typically happens from datacenter/server IP addresses. "
            "Run spotdl from a regular home or office network, or supply "
            "--client-id and --client-secret instead."
        )

    if not resp.ok:
        raise SpotifyAnonError(
            f"Unexpected HTTP {resp.status_code} from Spotify token endpoint: {resp.text[:200]}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise SpotifyAnonError(
            f"Could not parse Spotify token response: {resp.text[:200]}"
        ) from exc

    if "error" in data:
        raise SpotifyAnonError(
            f"Spotify returned an error: {data['error']}. "
            "The anonymous token endpoint may have changed. "
            "Use --client-id and --client-secret as a fallback."
        )

    token = data.get("accessToken")
    if not token:
        raise SpotifyAnonError(
            f"No accessToken in Spotify response: {list(data.keys())}"
        )

    expiry = data.get("accessTokenExpirationTimestampMs", 0)
    logger.debug(
        "Obtained anonymous Spotify token (expires at %s, isAnonymous=%s)",
        expiry,
        data.get("isAnonymous"),
    )
    return token, expiry
