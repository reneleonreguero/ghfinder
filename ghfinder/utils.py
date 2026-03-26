"""Shared utilities: session creation, rate limiting, pagination."""

import os
import re
import time

import requests
from rich.console import Console

console = Console(stderr=True)

GITHUB_API = "https://api.github.com"


def create_session(token: str | None = None) -> requests.Session:
    """Build a requests.Session with GitHub auth headers."""
    token = token or os.environ.get("GITHUB_TOKEN")
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def rate_limit_handler(response: requests.Response) -> None:
    """Check rate limit headers and sleep if exhausted."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
    if remaining == 0:
        reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(0, reset_ts - time.time()) + 1
        console.print(
            f"[yellow]Rate limit reached. Waiting {wait:.0f}s...[/yellow]",
            highlight=False,
        )
        time.sleep(wait)


def gh_get(
    session: requests.Session, url: str, params: dict | None = None
) -> requests.Response:
    """GET request with error handling and rate limit awareness."""
    if not url.startswith("http"):
        url = GITHUB_API + url

    for attempt in range(2):
        resp = session.get(url, params=params, timeout=30)
        rate_limit_handler(resp)

        if resp.status_code == 200:
            return resp
        if resp.status_code in (403, 429):
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else 60
            if attempt == 0:
                console.print(
                    f"[yellow]Secondary rate limit hit. Waiting {wait}s...[/yellow]",
                    highlight=False,
                )
                time.sleep(wait)
                continue
        if resp.status_code == 401:
            raise RuntimeError("GitHub API: 401 Unauthorized — check your token.")
        if resp.status_code == 404:
            return resp  # caller handles missing resources
        if resp.status_code == 422:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            raise RuntimeError(f"GitHub API: 422 Unprocessable — {msg}")
        resp.raise_for_status()

    resp.raise_for_status()
    return resp  # unreachable but satisfies type checkers


def paginate(
    session: requests.Session,
    url: str,
    params: dict,
    max_results: int = 100,
) -> list[dict]:
    """Fetch all pages up to max_results items."""
    items: list[dict] = []
    params = dict(params)
    params.setdefault("per_page", 100)

    while url and len(items) < max_results:
        resp = gh_get(session, url, params)
        if resp.status_code != 200:
            break
        data = resp.json()

        # Search API wraps results in {"items": [...]}
        page_items = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(page_items, list):
            break

        items.extend(page_items)

        # Follow Link header for next page
        link_header = resp.headers.get("Link", "")
        next_url = _parse_next_link(link_header)
        url = next_url
        params = {}  # params are already encoded in the next URL

    return items[:max_results]


def _parse_next_link(link_header: str) -> str | None:
    """Extract the 'next' URL from a GitHub Link header."""
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def is_authenticated(session: requests.Session) -> bool:
    """Check if session has a valid token."""
    return "Authorization" in session.headers
