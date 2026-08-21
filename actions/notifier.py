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
            body="오늘 KBO 경기가 시작되었습니다.",
        ),
        topic=TOPIC_GAME_START,
    )
    message_id = messaging.send(message)
    logger.info("Sent game-start push: %s", message_id)
    return message_id


def send_game_end_push(magic_number_result: dict) -> str:
    """Notify subscribers that today's games are over and the magic number changed."""
    _ensure_initialized()
    target = magic_number_result["targetTeam"]
    magic_number = target["magicNumber"]
    summary = magic_number_result.get("todayGamesStatus", {}).get("summary", "")

    message = messaging.Message(
        notification=messaging.Notification(
            title="매직넘버 갱신 알림",
            body=summary or f"{target['name']}의 매직넘버가 {magic_number}(으)로 갱신되었습니다.",
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
