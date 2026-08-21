"""KBO magic number calculation engine.

All win-rate math uses `fractions.Fraction` (wins/losses are always integers)
so tie-boundary comparisons are exact -- no floating point error can flip a
result at the exact threshold where a team clinches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional


@dataclass(frozen=True)
class TeamRecord:
    name: str
    wins: int
    losses: int
    draws: int
    remaining_games: int
    game_behind: float = 0.0
    rank: Optional[int] = None


def win_rate(wins: int, losses: int) -> Fraction:
    """KBO win rate: wins / (wins + losses). Draws are excluded entirely."""
    decided = wins + losses
    if decided == 0:
        return Fraction(0)
    return Fraction(wins, decided)


def compute_magic_number(
    target: TeamRecord,
    chaser: TeamRecord,
    head_to_head_advantage: bool = False,
) -> int:
    """
    Minimum number of additional wins `target` needs from its own remaining
    games so that -- even in the worst case where it loses every other
    remaining game -- its final win rate strictly exceeds the best possible
    final win rate `chaser` could still reach (chaser winning out).

    Derivation: let D = target.wins + target.losses + target.remaining_games.
    If target wins x of its remaining games and loses the rest, its final
    decided-game count is always D regardless of x (only the split between
    wins/losses among the remaining games changes), so its final win rate is
    simply (target.wins + x) / D -- strictly increasing in x. We solve for
    the smallest integer x in that expression that beats chaser's ceiling
    win rate. This mirrors the standard MLB/KBO magic-number convention of
    assuming no further draws occur in anyone's remaining games.

    `head_to_head_advantage=True` means target has already clinched the
    season head-to-head tiebreaker against chaser, so a *tied* final win
    rate still clinches the race for target -- the comparison becomes
    non-strict (>=) instead of strict (>). The Naver Sports endpoints used
    by this pipeline don't expose head-to-head records, so callers must
    supply this manually (see HEAD_TO_HEAD_ADVANTAGE in the README).

    Returns 0 if the race is already mathematically clinched.
    """
    decided_total = target.wins + target.losses + target.remaining_games
    if decided_total <= 0:
        return 0

    chaser_best_wins = chaser.wins + chaser.remaining_games
    chaser_best_wr = win_rate(chaser_best_wins, chaser.losses)

    # Solve (target.wins + x) / decided_total  {>=, >}  chaser_best_wr  for x.
    threshold = chaser_best_wr * decided_total - target.wins

    if head_to_head_advantage:
        x_min = math.ceil(threshold)
    else:
        x_min = math.floor(threshold) + 1

    return max(0, x_min)


def build_result_payload(
    season: int,
    target: TeamRecord,
    chaser: TeamRecord,
    magic_number: int,
    is_all_finished: bool,
    has_cancelled: bool,
    summary: str,
    updated_at_iso: str,
) -> dict:
    """Assemble the magic_number.json payload matching the published schema."""
    return {
        "updatedAt": updated_at_iso,
        "season": season,
        "targetTeam": {
            "name": target.name,
            "rank": target.rank,
            "wins": target.wins,
            "losses": target.losses,
            "draws": target.draws,
            "remainingGames": target.remaining_games,
            "magicNumber": magic_number,
            "tragicNumber": None,
        },
        "runnerUpTeam": {
            "name": chaser.name,
            "rank": chaser.rank,
            "wins": chaser.wins,
            "losses": chaser.losses,
            "draws": chaser.draws,
            "remainingGames": chaser.remaining_games,
            "gamesBehind": chaser.game_behind,
        },
        "todayGamesStatus": {
            "isAllFinished": is_all_finished,
            "hasCancelled": has_cancelled,
            "summary": summary,
        },
    }
