import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from web import validate  # noqa: E402

CALS = [{"name": "personal", "id": "primary"}, {"name": "work", "id": "primary"}]


def test_valid_config():
    rule = {"source": "personal", "target": "work", "work_hour_start": 9, "work_hour_end": 18, "workdays": [0, 4], "pause_on": ["Vacations"]}
    assert validate({"sync_interval_seconds": 300, "calendars": CALS, "sync": [rule]}) == []


def test_rejects_bad_config():
    assert validate({"calendars": [{"name": "../evil", "id": "x"}]})  # name becomes a file path
    assert validate({"calendars": CALS + [{"name": "work", "id": "x"}]})  # duplicate
    assert validate({"calendars": CALS, "sync": [{"source": "personal", "target": "nope"}]})
    assert validate({"calendars": CALS, "sync": [{"source": "work", "target": "work"}]})
    assert validate({"calendars": CALS, "sync": [{"source": "personal", "target": "work", "work_hour_start": 9}]})
    assert validate({"calendars": CALS, "sync": [{"source": "personal", "target": "work", "workdays": [7]}]})
