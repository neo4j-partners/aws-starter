"""Generated maintenance events trace to readings, and output is deterministic."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from generator.fleet import entry_into_service
from generator.main import generate
from generator.specs import ENGINE_SPECS, SENSOR_FAULT_MAP

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


@pytest.fixture(scope="module")
def large_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30 aircraft over 90 days: about 240 events, enough to cover every fault."""
    output = tmp_path_factory.mktemp("large")
    generate(aircraft=30, airports=40, days=90, seed=SEED, output=output)
    return output


def test_event_fault_matches_the_crossing_sensor(large_dataset: Path) -> None:
    model = {r[":ID(Aircraft)"]: r["model"] for r in _rows(large_dataset / "nodes_aircraft.csv")}
    sensor_type = {r[":ID(Sensor)"]: r["type"] for r in _rows(large_dataset / "nodes_sensors.csv")}
    events = _rows(large_dataset / "nodes_maintenance.csv")
    assert len(events) > 100, f"expected a large sample, got {len(events)} events"

    wanted = {(e["system_id"], e["reported_at"]) for e in events}
    values: dict[tuple[str, str], dict[str, float]] = {}
    for r in _rows(large_dataset / "nodes_readings.csv"):
        key = (r["sensor_id"].rsplit("-SN", 1)[0], r["ts"])
        if key in wanted:
            values.setdefault(key, {})[sensor_type[r["sensor_id"]]] = float(r["value"])

    for e in events:
        spec = ENGINE_SPECS[model[e["aircraft_id"]]]
        v = values.get((e["system_id"], e["reported_at"]), {})
        thresholds = {
            "EGT": (spec.egt_warning, spec.egt_critical),
            "Vibration": (spec.vib_warning, spec.vib_critical),
        }
        # Some sensor crossed warning at this hour, the fault is one that
        # sensor maps to, and a CRITICAL event's sensor is at or above critical.
        explained = [
            sensor
            for sensor, (warning, critical) in thresholds.items()
            if v.get(sensor, 0.0) >= warning
            and (e["fault"], e["severity"]) in SENSOR_FAULT_MAP[sensor]
            and (e["severity"] != "CRITICAL" or v[sensor] >= critical)
        ]
        assert explained, f"{e[':ID(MaintenanceEvent)']} {e['fault']} {e['severity']}: {v}"


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


def _removals_with_entry_into_service(
    dataset: Path,
) -> list[tuple[dict[str, str], datetime]]:
    in_service = {
        r[":ID(Aircraft)"]: datetime.combine(
            entry_into_service(r["model"], r["tail_number"]), datetime.min.time()
        )
        for r in _rows(dataset / "nodes_aircraft.csv")
    }
    return [(r, in_service[r["aircraft_id"]]) for r in _rows(dataset / "nodes_removals.csv")]


def test_airframe_hours_follow_days_in_service(large_dataset: Path) -> None:
    removals = _removals_with_entry_into_service(large_dataset)
    by_aircraft: dict[str, list[dict[str, str]]] = {}
    for r, in_service in removals:
        days = (datetime.fromisoformat(r["removal_date"]) - in_service).total_seconds() / 86400
        # 8 to 10 flight hours a day since entry into service.
        assert 7.99 <= int(r["flight_hours_at_removal"]) / days <= 10.01, r[":ID(Removal)"]
        by_aircraft.setdefault(r["aircraft_id"], []).append(r)

    repeat = [rows for rows in by_aircraft.values() if len(rows) > 1]
    assert len(repeat) >= 5, "expected several aircraft with more than one removal"
    for rows in repeat:
        rows.sort(key=lambda r: r["removal_date"])
        hours = [int(r["flight_hours_at_removal"]) for r in rows]
        assert hours == sorted(hours), (rows[0]["aircraft_id"], hours)


def test_install_date_is_after_entry_into_service(large_dataset: Path) -> None:
    for r, in_service in _removals_with_entry_into_service(large_dataset):
        assert datetime.fromisoformat(r["installation_date"]) > in_service, r[":ID(Removal)"]


def test_same_seed_gives_identical_output(dataset: Path, tmp_path: Path) -> None:
    rerun = _generate(tmp_path)
    files = sorted(p.name for p in dataset.glob("*.csv"))
    assert files == sorted(p.name for p in rerun.glob("*.csv"))
    for name in files:
        assert (dataset / name).read_bytes() == (rerun / name).read_bytes(), name


# 45 aircraft run past the 30 registry tails, so the extra aircraft's model
# and operator shuffles, generated tails, and icao24 assignment all run.
HASH_AIRCRAFT, HASH_DAYS = 45, 3

_GENERATE_SCRIPT = (
    "import sys; from pathlib import Path; from generator.main import generate; "
    f"generate(aircraft={HASH_AIRCRAFT}, airports=40, days={HASH_DAYS}, seed={SEED}, "
    "output=Path(sys.argv[1]))"
)


def test_same_seed_is_identical_across_hash_seeds(tmp_path: Path) -> None:
    """Two processes with different string hashing write the same bytes.

    String hashing changes set and dict-of-set iteration order between
    processes, which an in-process rerun cannot catch.
    """
    baseline = tmp_path / "in_process"
    generate(aircraft=HASH_AIRCRAFT, airports=40, days=HASH_DAYS, seed=SEED, output=baseline)
    files = sorted(p.name for p in baseline.glob("*.csv"))
    for hash_seed in ("0", "1"):
        output = tmp_path / f"hash_{hash_seed}"
        subprocess.run(
            [sys.executable, "-c", _GENERATE_SCRIPT, str(output)],
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            check=True,
            capture_output=True,
        )
        assert files == sorted(p.name for p in output.glob("*.csv"))
        for name in files:
            assert (baseline / name).read_bytes() == (output / name).read_bytes(), (
                hash_seed,
                name,
            )
