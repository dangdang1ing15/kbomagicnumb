import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator import TeamRecord, compute_magic_number  # noqa: E402


def test_typical_race_matches_classic_formula():
    # Classic magic number = (chaser_remaining + 1) - (target_wins - chaser_wins)
    # = (22 + 1) - (75 - 71) = 19. Only coincides with the win-rate formula
    # when target/chaser end up playing the same number of decided games;
    # verified by hand here as a sanity cross-check.
    target = TeamRecord(name="A", wins=75, losses=45, draws=2, remaining_games=22, rank=1)
    chaser = TeamRecord(name="B", wins=71, losses=48, draws=3, remaining_games=22, rank=2)
    assert compute_magic_number(target, chaser) == 19


def test_already_clinched_returns_zero():
    target = TeamRecord(name="A", wins=90, losses=40, draws=0, remaining_games=2, rank=1)
    chaser = TeamRecord(name="B", wins=70, losses=60, draws=0, remaining_games=12, rank=2)
    assert compute_magic_number(target, chaser) == 0


def test_head_to_head_advantage_allows_tie_to_clinch():
    # Constructed so target's win rate lands exactly on chaser's ceiling at x=4:
    # chaser ceiling = (70+20)/(70+20+60) = 90/150 = 0.6
    # target decided_total = 80+50+10 = 140; at x=4 -> 84/140 = 0.6 (exact tie)
    target = TeamRecord(name="A", wins=80, losses=50, draws=0, remaining_games=10, rank=1)
    chaser = TeamRecord(name="B", wins=70, losses=60, draws=0, remaining_games=20, rank=2)

    # Without a head-to-head tiebreaker edge, a tie doesn't clinch -> need one more win.
    assert compute_magic_number(target, chaser, head_to_head_advantage=False) == 5
    # With the tiebreaker already secured, the exact tie is enough.
    assert compute_magic_number(target, chaser, head_to_head_advantage=True) == 4


def test_magic_number_never_negative():
    target = TeamRecord(name="A", wins=120, losses=10, draws=0, remaining_games=14, rank=1)
    chaser = TeamRecord(name="B", wins=50, losses=80, draws=0, remaining_games=14, rank=2)
    assert compute_magic_number(target, chaser) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
