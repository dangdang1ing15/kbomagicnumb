"""FCM topic push notifications via firebase-admin."""
from __future__ import annotations

import json
import logging
import os
import threading

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

TOPIC_GAME_START = "kbo-magic-number-start"
TOPIC_TEAM_RESULT = "kbo-magic-number-team-result"
TOPIC_GAME_END = "kbo-magic-number-end"

_init_lock = threading.Lock()
_initialized = False


def _ensure_initialized() -> None:
    """Initialize the firebase-admin app once per Cloud Function instance."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        creds_json = os.environ.get("FIREBASE_CREDENTIALS")
        if creds_json:
            cred = credentials.Certificate(json.loads(creds_json))
            firebase_admin.initialize_app(cred)
        else:
            # Falls back to Application Default Credentials, which Cloud
            # Functions supplies automatically via its runtime service account.
            firebase_admin.initialize_app()
        _initialized = True


def send_game_start_push() -> str:
    """Notify subscribers that today's KBO games have started (send once/day)."""
    _ensure_initialized()
    message = messaging.Message(
        notification=messaging.Notification(
            title="KBO 경기 시작",
            body="게임이 시작되었어요! 과연 매직넘버는 어떻게 갱신될까요?",
        ),
        topic=TOPIC_GAME_START,
    )
    message_id = messaging.send(message)
    logger.info("Sent game-start push: %s", message_id)
    return message_id


def send_target_team_result_push(team_name: str, won: bool, team_score: int, opponent_score: int) -> str:
    """Notify subscribers that the target team's own game finished (send once/day)."""
    _ensure_initialized()
    result_word = "승리" if won else "패배"
    message = messaging.Message(
        notification=messaging.Notification(
            title=f"{team_name} 경기 종료",
            body=(
                f"내 팀이 {result_word}했어요! ({team_score}:{opponent_score}) "
                "다른 팀들의 경기가 다 끝나면 매직넘버를 알려드릴게요."
            ),
        ),
        data={
            "team_name": team_name,
            "won": "true" if won else "false",
        },
        topic=TOPIC_TEAM_RESULT,
    )
    message_id = messaging.send(message)
    logger.info("Sent team-result push: %s", message_id)
    return message_id


def send_game_end_push(magic_number_result: dict) -> str:
    """Notify subscribers that today's games are over and the magic number changed."""
    _ensure_initialized()
    target = magic_number_result["targetTeam"]
    magic_number = target["magicNumber"]

    message = messaging.Message(
        notification=messaging.Notification(
            title="매직넘버 갱신 알림",
            body="모든 경기가 다 끝났어요! 갱신된 매직넘버를 확인해주세요.",
        ),
        data={
            "reload_widget": "true",
            "magic_number": str(magic_number),
        },
        topic=TOPIC_GAME_END,
    )
    message_id = messaging.send(message)
    logger.info("Sent game-end push: %s", message_id)
    return message_id
