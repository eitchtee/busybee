import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from sync import is_blocked  # noqa: E402


def ev(start, end):
    return {"start": {"dateTime": start}, "end": {"dateTime": end}}


ALL_DAY = [(datetime(2026, 11, 12), datetime(2026, 11, 14))]  # 12th and 13th, end exclusive
TIMED = [(datetime.fromisoformat("2026-11-12T13:00:00-03:00"), datetime.fromisoformat("2026-11-12T15:00:00-03:00"))]


def test_all_day_uses_event_local_time():
    # 22:00 local on the 13th is 01:00 UTC on the 14th; still blocked
    assert is_blocked(ev("2026-11-13T22:00:00-03:00", "2026-11-13T23:00:00-03:00"), ALL_DAY)
    # 22:00 local on the 11th is 01:00 UTC on the 12th; not blocked
    assert not is_blocked(ev("2026-11-11T22:00:00-03:00", "2026-11-11T23:00:00-03:00"), ALL_DAY)
    # day after the blocker
    assert not is_blocked(ev("2026-11-14T00:00:00-03:00", "2026-11-14T01:00:00-03:00"), ALL_DAY)


def test_timed_partial_overlap_blocks_touching_does_not():
    assert is_blocked(ev("2026-11-12T14:30:00-03:00", "2026-11-12T16:00:00-03:00"), TIMED)
    assert is_blocked(ev("2026-11-12T16:30:00Z", "2026-11-12T17:00:00Z"), TIMED)  # 13:30 -03
    assert not is_blocked(ev("2026-11-12T15:00:00-03:00", "2026-11-12T16:00:00-03:00"), TIMED)


def test_no_ranges():
    assert not is_blocked(ev("2026-11-12T14:00:00-03:00", "2026-11-12T15:00:00-03:00"), [])
    assert not is_blocked(ev("2026-11-12T14:00:00-03:00", "2026-11-12T15:00:00-03:00"), None)
