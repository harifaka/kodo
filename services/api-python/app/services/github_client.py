"""Minimal GitHub API client for pull-request creation (Phase 6).

Only ``POST /repos/{owner}/{repo}/pulls`` is used. The token is attached to that single request and
never stored or logged. Tests inject an ``httpx.MockTransport`` so no network access is required.
"""

from __future__ import annotations

import re

import httpx

from app.services.audit_log import redact
from app.services.git_errors import GitRemoteError

GITHUB_API = "https://api.github.com"
PR_TIMEOUT_SECONDS = 30

_GITHUB_REMOTE = re.compile(
    r"^(?:https://(?:www\.)?github\.com/|git@github\.com:)(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]{0,99})/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]{0,99}?)(?:\.git)?/?$"
)

# Tests inject an httpx.MockTransport here so PR creation never needs the network.
_transport_override: httpx.BaseTransport | None = None


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


def parse_github_remote(remote_url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a GitHub remote URL, or ``None`` for any other host."""
    match = _GITHUB_REMOTE.fullmatch((remote_url or "").strip())
    if match is None:
        return None
    return match.group("owner"), match.group("repo")


def create_pull_request(
    *, owner: str, repo: str, head: str, base: str, title: str, body: str, token: str
) -> str:
    """Open a pull request and return its ``html_url``. Raises :class:`GitRemoteError` on failure."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"title": title, "head": head, "base": base, "body": body}
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"

    try:
        with httpx.Client(timeout=PR_TIMEOUT_SECONDS, transport=_transport_override) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise GitRemoteError(504, "PR_TIMEOUT", "GitHub did not answer the pull-request request in time.") from exc
    except httpx.HTTPError as exc:
        raise GitRemoteError(
            502,
            "PR_FAILED",
            "Could not reach the GitHub API. Check network access and retry.",
        ) from exc

    if response.status_code >= 400:
        raise GitRemoteError(
            502,
            "PR_FAILED",
            f"GitHub rejected the pull request (HTTP {response.status_code}).{_github_message(response)}",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise GitRemoteError(502, "PR_FAILED", "The GitHub API returned a non-JSON response.") from exc

    html_url = data.get("html_url") if isinstance(data, dict) else None
    if not isinstance(html_url, str) or not html_url.startswith("https://"):
        raise GitRemoteError(502, "PR_FAILED", "The GitHub API response did not contain a pull-request URL.")
    return html_url


def _github_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    message = body.get("message")
    return f" GitHub said: {redact(str(message))[:300]}" if message else ""


__all__ = [
    "GITHUB_API",
    "create_pull_request",
    "parse_github_remote",
    "set_transport_override",
]
