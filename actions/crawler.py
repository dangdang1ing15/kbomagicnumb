"""Naver Sports (mobile, unofficial) REST API client for KBO schedule & standings.

Field names below were verified against the live endpoints (2025-08 season
data), not the commonly-circulated unofficial docs, which are stale in a few
places -- see the project plan for the specific corrections:

- The category filter query param is `categoryId=kbo`. `upperCategoryId=kbo`
  returns HTTP 200 but an always-empty game list.
- Game fields are `homeTeamScore`/`awayTeamScore` (not `homeScore`/`awayScore`),
  and there is no `currentInning` field -- inning progress comes back as a
  Korean string in `statusInfo` (e.g. "9회말").
- Standings fields are `teamId`, `teamName`, `ranking`, `winGameCount`,
  `loseGameCount`, `drawnGameCount`, `gameCount`, `gameBehind`. There is no
  remaining-games field; it's derived from a fixed season game count.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Optional

import requests

from calculator import TeamRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://api-gw.sports.naver.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.sports.naver.com/",
}
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

KBO_TOTAL_GAMES_DEFAULT = 144

_session = requests.Session()
_session.headers.update(HEADERS)


def _get(url: str, params: dict) -> dict:
    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("success", False):
                raise RuntimeError(f"Naver API returned failure: {payload}")
            return payload["result"]
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised after MAX_RETRIES
            last_error = exc
            logger.warning("Naver API request failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"Naver API request failed after {MAX_RETRIES} attempts") from last_error


def fetch_games(target_date: date) -> list[dict]:
    """Fetch KBO games scheduled for `target_date`, normalized to a stable shape."""
    date_str = target_date.strftime("%Y-%m-%d")
    result = _get(
        f"{BASE_URL}/schedule/games",
        params={
            "fields": "basic,superSchedule",
            "categoryId": "kbo",
            "fromDate": date_str,
            "toDate": date_str,
        },
    )
    games = []
    for g in result.get("games", []):
        games.append(
            {
                "gameId": g.get("gameId"),
                "gameDateTime": g.get("gameDateTime"),
                "homeTeamName": g.get("homeTeamName"),
                "awayTeamName": g.get("awayTeamName"),
                "homeScore": g.get("homeTeamScore"),
                "awayScore": g.get("awayTeamScore"),
                "statusCode": g.get("statusCode"),
                "statusInfo": g.get("statusInfo"),
                "winner": g.get("winner"),
                "cancelled": bool(g.get("cancel")),
                "suspended": bool(g.get("suspended")),
            }
        )
    return games


def fetch_standings(season: int) -> list[dict]:
    """Fetch KBO regular-season standings for `season`, sorted by rank."""
    total_games = int(os.environ.get("KBO_TOTAL_GAMES", KBO_TOTAL_GAMES_DEFAULT))
    result = _get(f"{BASE_URL}/statistics/categories/kbo/seasons/{season}/teams", params={})
    teams = []
    for t in result.get("seasonTeamStats", []):
        games_played = t.get("gameCount", 0)
        teams.append(
            {
                "teamId": t.get("teamId"),
                "teamName": t.get("teamName"),
                "rank": t.get("ranking"),
                "wins": t.get("winGameCount", 0),
                "losses": t.get("loseGameCount", 0),
                "draws": t.get("drawnGameCount", 0),
                "gamesPlayed": games_played,
                "remainingGames": max(0, total_games - games_played),
                "gameBehind": t.get("gameBehind", 0.0),
            }
        )
    teams.sort(key=lambda t: (t["rank"] is None, t["rank"]))
    return teams


def get_target_and_chaser(
    standings: list[dict],
    target_team_code: Optional[str] = None,
) -> tuple[TeamRecord, TeamRecord]:
    """
    Pick the target team and its immediate chaser (the team directly below it
    in the standings). Defaults to the league leader (rank 1) vs. rank 2 when
    `target_team_code` is not given.
    """
    if not standings:
        raise ValueError("standings is empty")

    if target_team_code:
        idx = next((i for i, t in enumerate(standings) if t["teamId"] == target_team_code), None)
        if idx is None:
            raise ValueError(f"team code {target_team_code!r} not found in standings")
    else:
        idx = 0

    if idx + 1 >= len(standings):
        raise ValueError("target team has no chaser below it in the standings")

    return _to_team_record(standings[idx]), _to_team_record(standings[idx + 1])


def _to_team_record(team: dict) -> TeamRecord:
    return TeamRecord(
        name=team["teamName"],
        wins=team["wins"],
        losses=team["losses"],
        draws=team["draws"],
        remaining_games=team["remainingGames"],
        game_behind=team["gameBehind"],
        rank=team["rank"],
    )
