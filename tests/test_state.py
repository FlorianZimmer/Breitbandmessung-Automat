import json
from datetime import date as real_date

import breitbandmessung_automate_stateful as bbm


class FakeDate(real_date):
    _today = real_date(2026, 1, 7)

    @classmethod
    def today(cls):
        return cls._today


def test_load_state_defaults_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(bbm, "date", FakeDate)
    path = tmp_path / "state.json"
    st = bbm.load_state(str(path))
    assert st["day_goal"] == 10
    assert st["campaign_goal"] == 30
    assert st["campaign_done"] == 0
    assert st["current_day"] == "2026-01-07"
    assert st["day_done"] == 0
    assert st["last_start"] is None
    assert st["last_end"] is None
    assert st["measurement_days"] == []


def test_save_state_writes_json(monkeypatch, tmp_path):
    monkeypatch.setattr(bbm, "date", FakeDate)
    path = tmp_path / "state.json"
    st = {"a": 1, "b": "x"}
    bbm.save_state(str(path), st)
    assert json.loads(path.read_text(encoding="utf-8")) == st
    assert not (tmp_path / "state.json.tmp").exists()


def test_ensure_day_rollover_resets_fields(monkeypatch):
    monkeypatch.setattr(bbm, "date", FakeDate)
    state = {
        "current_day": "2026-01-06",
        "day_done": 5,
        "last_start": "x",
        "last_end": "y",
    }
    bbm.ensure_day_rollover(state)
    assert state["current_day"] == "2026-01-07"
    assert state["day_done"] == 0
    assert state["last_start"] is None
    assert state["last_end"] is None


def test_record_measurement_day_adds_once(monkeypatch):
    monkeypatch.setattr(bbm, "date", FakeDate)
    state = {"current_day": "2026-01-07"}
    bbm.record_measurement_day(state)
    bbm.record_measurement_day(state)
    assert state["measurement_days"] == ["2026-01-07"]


def test_calendar_gap_ok(monkeypatch):
    monkeypatch.setattr(bbm, "date", FakeDate)

    assert bbm.calendar_gap_ok({"measurement_days": []}) is True

    FakeDate._today = real_date(2026, 1, 7)
    assert bbm.calendar_gap_ok({"measurement_days": ["2026-01-06"]}) is False
    assert bbm.calendar_gap_ok({"measurement_days": ["2026-01-05"]}) is True

