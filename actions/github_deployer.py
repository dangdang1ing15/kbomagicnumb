"""GitHub Contents API wrapper for committing JSON files (magic_number.json, state.json).

Uses plain `requests` rather than PyGithub to keep the Cloud Function's cold
start light -- this pipeline only ever needs three Contents API calls.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 10


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _contents_url(repo: str, path: str) -> str:
    return f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}"


def get_sha(repo: str, path: str, token: str, branch: str = "main") -> Optional[str]:
    """Return the current blob sha for `path`, or None if it doesn't exist yet."""
    resp = requests.get(
        _contents_url(repo, path),
        headers=_headers(token),
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()["sha"]


def download_json(repo: str, path: str, token: str, branch: str = "main") -> Optional[dict]:
    """Fetch and decode `path` as JSON, or None if it doesn't exist yet."""
    resp = requests.get(
        _contents_url(repo, path),
        headers=_headers(token),
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    content_b64 = resp.json()["content"]
    raw = base64.b64decode(content_b64)
    return json.loads(raw.decode("utf-8"))


def upload_json(
    repo: str,
    path: str,
    data: dict,
    token: str,
    message: str,
    branch: str = "main",
) -> dict:
    """Create or overwrite `path` in `repo` with `data` serialized as pretty JSON.

    Looks up the existing blob sha first so this is a safe overwrite rather
    than a blind create (GitHub rejects a PUT without `sha` if the file
    already exists).
    """
    sha = get_sha(repo, path, token, branch=branch)
    body_json = json.dumps(data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(body_json.encode("utf-8")).decode("ascii")

    payload = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(
        _contents_url(repo, path),
        headers=_headers(token),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    logger.info("Committed %s to %s@%s", path, repo, branch)
    return resp.json()
