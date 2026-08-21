"""Pipeline state-machine persistence, backed by a JSON file committed to GitHub.

Chosen over Firestore or an in-memory cache: Cloud Functions instances are
stateless between invocations so an in-memory cache doesn't survive, and
Firestore would require enabling another GCP API purely to store one small
document. Reusing the GitHub Contents API path already used to publish
magic_number.json keeps this to zero extra GCP surface area/cost.
"""
from __future__ import annotations

from datetime import date

import github_deployer

DEFAULT_STATE_PATH = "data/state.json"


def _default_state(today: str) -> dict:
    return {
        "date": today,
        "gameStartNotified": False,
        "targetTeamResultNotified": False,
        "allFinishedNotified": False,
        "lastMagicNumber": None,
    }


def load_state(repo: str, token: str, path: str = DEFAULT_STATE_PATH, branch: str = "main") -> dict:
    """Load today's pipeline state, resetting automatically when the date rolls over."""
    today = date.today().isoformat()
    state = github_deployer.download_json(repo, path, token, branch=branch)
    if state is None or state.get("date") != today:
        return _default_state(today)
    # Merge onto defaults so a schema change (new field added) doesn't KeyError
    # against a state.json written by an older deploy earlier the same day.
    return {**_default_state(today), **state}


def save_state(repo: str, token: str, state: dict, path: str = DEFAULT_STATE_PATH, branch: str = "main") -> None:
    github_deployer.upload_json(
        repo,
        path,
        state,
        token,
        message=f"chore(state): update pipeline state for {state.get('date')}",
        branch=branch,
    )
