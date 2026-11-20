"""Generated maintenance events trace to readings, and output is deterministic."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from generator.main import generate
from generator.specs import ENGINE_SPECS

AIRCRAFT, DAYS, SEED = 20, 30, 42


def _generate(output: Path, seed: int = SEED) -> Path:
    generate(aircraft=AIRCRAFT, airports=40, days=DAYS, seed=seed, output=output)
    return output


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate(tmp_path_factory.mktemp("run_a"))


def test_every_event_has_a_reading_at_or_above_warning(dataset: Path) -> None:
    model = {r[":ID(Aircraft)"]: r["model"] for r in _rows(dataset / "nodes_aircraft.csv")}
    sensor_type = {r[":ID(Sensor)"]: r["type"] for r in _rows(dataset / "nodes_sensors.csv")}
    events = _rows(dataset / "nodes_maintenance.csv")
    assert events, "expected at least one maintenance event"

    wanted = {(e["system_id"], e["reported_at"]) for e in events}
    values: dict[tuple[str, str], dict[str, float]] = {}
    for r in _rows(dataset / "nodes_readings.csv"):
        key = (r["sensor_id"].rsplit("-SN", 1)[0], r["ts"])
        if key in wanted:
            values.setdefault(key, {})[sensor_type[r["sensor_id"]]] = float(r["value"])

    for e in events:
        spec = ENGINE_SPECS[model[e["aircraft_id"]]]
        v = values.get((e["system_id"], e["reported_at"]), {})
        assert (
            v.get("EGT", 0.0) >= spec.egt_warning or v.get("Vibration", 0.0) >= spec.vib_warning
        ), f"{e[':ID(MaintenanceEvent)']} has no reading at or above warning"


def test_reading_number_is_hour_offset(dataset: Path) -> None:
    readings = _rows(dataset / "nodes_readings.csv")
    start = {}
    for r in readings:
        start.setdefault(r["sensor_id"], datetime.fromisoformat(r["ts"]))
    for r in readings:
        sensor_id, number = r["reading_id"].rsplit("-R", 1)
        assert sensor_id == r["sensor_id"]
        hours = (datetime.fromisoformat(r["ts"]) - start[sensor_id]).total_seconds() / 3600
        assert int(number) == hours, r["reading_id"]
    assert readings[0]["reading_id"].endswith("-R00000")


def test_removal_hours_agree_with_install_date(dataset: Path) -> None:
    removals = _rows(dataset / "nodes_removals.csv")
    assert removals, "expected at least one removal"
    for r in removals:
        hours = float(r["time_since_install"])
        assert hours < float(r["flight_hours_at_removal"]), r[":ID(Removal)"]
        installed = datetime.fromisoformat(r["installation_date"])
        days = (datetime.fromisoformat(r["removal_date"]) - installed).total_seconds() / 86400
        # 8 to 10 flight hours a day, with slack for whole-second dates.
        assert 7.99 <= hours / days <= 10.01, r[":ID(Removal)"]


def test_same_seed_gives_identical_output(dataset: Path, tmp_path: Path) -> None:
    rerun = _generate(tmp_path)
    files = sorted(p.name for p in dataset.glob("*.csv"))
    assert files == sorted(p.name for p in rerun.glob("*.csv"))
    for name in files:
        assert (dataset / name).read_bytes() == (rerun / name).read_bytes(), name
