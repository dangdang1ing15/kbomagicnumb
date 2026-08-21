"""Cloud Functions (2nd gen, HTTP-triggered) entry point for the KBO magic
number pipeline.

Cloud Scheduler calls `magic_number_pipeline` on a cron (see README.md for
the job definitions). The handler is idempotent -- all "did we already do
this today" decisions are driven by state.json in GitHub -- so it's safe for
Scheduler to call it every 2 minutes during game windows without causing
duplicate pushes or commits.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import functions_framework

import calculator
import crawler
import github_deployer
import notifier
import state_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

STARTED_STATUSES = {"PROGRESS", "RESULT", "SUSPENDED"}
FINISHED_STATUSES = {"RESULT", "CANCEL"}


def _env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _summarize_today(games: list[dict]) -> str:
    if not games:
        return "오늘 예정된 경기가 없습니다."
    parts = []
    for g in games:
        if g["statusCode"] == "CANCEL":
            parts.append(f"{g['homeTeamName']} vs {g['awayTeamName']} 취소")
        elif g["statusCode"] in ("RESULT", "SUSPENDED"):
            parts.append(f"{g['homeTeamName']} {g['homeScore']}:{g['awayScore']} {g['awayTeamName']}")
    return ", ".join(parts) if parts else "경기 진행 중입니다."


def _find_team_game(games: list[dict], team_code: Optional[str]) -> Optional[dict]:
    if not team_code:
        return None
    return next((g for g in games if team_code in (g["homeTeamCode"], g["awayTeamCode"])), None)


@functions_framework.http
def magic_number_pipeline(request):
    github_repo = _env("GITHUB_REPO", required=True)
    github_token = _env("GITHUB_TOKEN", required=True)
    json_path = _env("GITHUB_JSON_PATH", "magic_number.json")
    state_path = _env("GITHUB_STATE_PATH", state_store.DEFAULT_STATE_PATH)
    branch = _env("GITHUB_BRANCH", "main")
    season = int(_env("KBO_SEASON", str(date.today().year)))
    target_team_code = _env("TARGET_TEAM_CODE") or None
    head_to_head_advantage = _env("HEAD_TO_HEAD_ADVANTAGE", "false").lower() == "true"
    season_end_date = date.fromisoformat(_env("KBO_SEASON_END_DATE", f"{season}-10-05"))

    today = datetime.now(KST).date()
    games = crawler.fetch_games(today)
    state = state_store.load_state(github_repo, github_token, path=state_path, branch=branch)
    state_changed = False

    # Standings are needed every invocation (not just once all games finish)
    # so we can identify which of today's games belongs to the target team.
    standings = crawler.fetch_standings(season)
    target, chaser = crawler.get_target_and_chaser(standings, target_team_code)

    started = any(g["statusCode"] in STARTED_STATUSES for g in games)
    if started and not state["gameStartNotified"]:
        notifier.send_game_start_push()
        state["gameStartNotified"] = True
        state_changed = True

    target_game = _find_team_game(games, target.team_code)
    if (
        target_game
        and target_game["statusCode"] == "RESULT"
        and not state["targetTeamResultNotified"]
    ):
        is_home = target_game["homeTeamCode"] == target.team_code
        team_score = target_game["homeScore"] if is_home else target_game["awayScore"]
        opponent_score = target_game["awayScore"] if is_home else target_game["homeScore"]
        winning_side = "HOME" if is_home else "AWAY"
        won = target_game["winner"] == winning_side
        notifier.send_target_team_result_push(target.name, won, team_score, opponent_score)
        state["targetTeamResultNotified"] = True
        state_changed = True

    all_finished = bool(games) and all(g["statusCode"] in FINISHED_STATUSES for g in games)
    has_cancelled = any(g["statusCode"] == "CANCEL" for g in games)

    if all_finished and not state["allFinishedNotified"]:
        magic_number = calculator.compute_magic_number(target, chaser, head_to_head_advantage)
        magic_number_table = calculator.build_magic_number_table(
            crawler.to_team_records(standings)
        )
        remaining_schedule = crawler.fetch_remaining_schedule(
            today + timedelta(days=1), season_end_date
        )

        payload = calculator.build_result_payload(
            season=season,
            target=target,
            chaser=chaser,
            magic_number=magic_number,
            is_all_finished=True,
            has_cancelled=has_cancelled,
            summary=_summarize_today(games),
            updated_at_iso=datetime.now(KST).isoformat(),
            standings=crawler.to_team_records(standings),
            magic_number_table=magic_number_table,
            remaining_schedule=remaining_schedule,
        )

        github_deployer.upload_json(
            github_repo,
            json_path,
            payload,
            github_token,
            message=f"chore(data): update magic number for {today.isoformat()}",
            branch=branch,
        )

        if state.get("lastMagicNumber") != magic_number:
            notifier.send_game_end_push(payload)

        state["allFinishedNotified"] = True
        state["lastMagicNumber"] = magic_number
        state_changed = True

    if state_changed:
        state_store.save_state(github_repo, github_token, state, path=state_path, branch=branch)

    return {"status": "ok", "date": today.isoformat(), "gameCount": len(games)}, 200
