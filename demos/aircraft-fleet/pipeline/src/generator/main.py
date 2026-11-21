"""CLI entry point for the aircraft dataset generator."""

from __future__ import annotations

import difflib
import errno
import fcntl
import json
import os
import random
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import manuals
from .config import GeneratorConfig
from .fleet import AircraftNode, generate_fleet
from .maintenance import generate_maintenance_events
from .operations import generate_operations
from .removals import _check_start_date, generate_removals
from .sensors import generate_system_readings
from .specs import EVENT_SEVERITIES
from .stamp import (
    LOCK_NAME,
    STAMP_NAME,
    GenerateRunningError,
    clear_stamp,
    regenerate_reason,
    stamp_for,
    write_stamp,
)
from .stats import STATS_CONFIG, fleet_stats
from .writers import CSV_COLUMNS, write_csv

app = typer.Typer(
    name="generate-data",
    help="Generate a synthetic aircraft digital twin dataset with correlated sensor degradation.",
    add_completion=False,
)
console = Console()


# Every file a run writes into the output directory, besides the stamp. A run
# removes the ones it did not write, so stale files cannot pass as current.
OUTPUT_FILES = frozenset(CSV_COLUMNS) | {"nodes_readings.csv"}
# Name prefix of the temp directory a run writes into before it publishes.
_WORK_PREFIX = ".generating-"


def _fleet_rows(
    fleet: list[AircraftNode],
) -> tuple[
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
]:
    """Flatten fleet topology into CSV-ready row lists."""
    aircraft_rows, system_rows, component_rows, sensor_rows = [], [], [], []
    rels_aircraft_system, rels_system_component, rels_system_sensor = [], [], []

    for ac in fleet:
        aircraft_rows.append(
            {
                ":ID(Aircraft)": ac.aircraft_id,
                "tail_number": ac.tail_number,
                "icao24": ac.icao24,
                "model": ac.model,
                "manufacturer": ac.manufacturer,
                "operator": ac.operator,
            }
        )
        for sys in ac.systems:
            system_rows.append(
                {
                    ":ID(System)": sys.system_id,
                    "aircraft_id": ac.aircraft_id,
                    "type": sys.type,
                    "name": sys.name,
                }
            )
            rels_aircraft_system.append(
                {":START_ID(Aircraft)": ac.aircraft_id, ":END_ID(System)": sys.system_id}
            )
            for comp in sys.components:
                component_rows.append(
                    {
                        ":ID(Component)": comp.component_id,
                        "system_id": sys.system_id,
                        "type": comp.type,
                        "name": comp.name,
                    }
                )
                rels_system_component.append(
                    {":START_ID(System)": sys.system_id, ":END_ID(Component)": comp.component_id}
                )
            for sensor in sys.sensors:
                sensor_rows.append(
                    {
                        ":ID(Sensor)": sensor.sensor_id,
                        "system_id": sys.system_id,
                        "type": sensor.type,
                        "name": sensor.name,
                        "unit": sensor.unit,
                    }
                )
                rels_system_sensor.append(
                    {":START_ID(System)": sys.system_id, ":END_ID(Sensor)": sensor.sensor_id}
                )

    return (
        aircraft_rows,
        system_rows,
        component_rows,
        sensor_rows,
        rels_aircraft_system,
        rels_system_component,
        rels_system_sensor,
    )


@app.command()
def generate(
    aircraft: int = typer.Option(100, "--aircraft", "-a", help="Number of aircraft to generate."),
    airports: int = typer.Option(40, "--airports", help="Number of airports (max 40)."),
    days: int = typer.Option(90, "--days", "-d", help="Days of sensor telemetry."),
    seed: int = typer.Option(42, "--seed", help="Random seed for reproducibility."),
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Output directory for CSV files.")
    ] = Path("."),
    if_stale: Annotated[
        bool,
        typer.Option(
            "--if-stale",
            help="Skip generation when the output's stamp matches this config and code.",
        ),
    ] = False,
) -> None:
    """Generate all CSV files for the aircraft digital twin dataset."""
    airports = min(airports, 40)
    config = GeneratorConfig(
        n_aircraft=aircraft,
        n_airports=airports,
        n_days=days,
        seed=seed,
        output_dir=output,
    )
    # Removals are generated last. Check their start date before any work.
    _check_start_date(config)
    output.mkdir(parents=True, exist_ok=True)
    stamp = stamp_for(config)
    with ExitStack() as stack:
        # Only a held lock becomes a message. Any other error keeps its
        # traceback.
        try:
            stack.enter_context(_exclusive_lock(output))
        except GenerateRunningError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]", soft_wrap=True)
            raise typer.Exit(1) from exc
        _remove_orphaned_work_dirs(output)
        if if_stale:
            if (reason := regenerate_reason(output, stamp)) is None:
                console.print(f"{output.resolve()} is current for this config and code. Skipping.")
                return
            console.print(f"Regenerating, since {reason}.")
        # Write the run into a temp directory, so a failure leaves the
        # previous output and its stamp as they were.
        work = Path(tempfile.mkdtemp(dir=output, prefix=_WORK_PREFIX))
        try:
            elapsed, summary = _write_dataset(config, work, stamp)
            _publish(work, output)
        finally:
            # Only a missing work dir is expected here. Any other cleanup
            # error, such as a permission problem, still shows.
            with suppress(FileNotFoundError):
                shutil.rmtree(work)
    _print_summary(config, *summary, elapsed)


@contextmanager
def _exclusive_lock(output: Path) -> Iterator[None]:
    """Hold the output's generate lock, or fail at once if another run holds it.

    A load holds the same lock shared, so this also fails while a load runs.

    The kernel releases the lock when the process exits, even on SIGKILL, so
    a temp dir found while holding it was left by a run that has ended.

    Raises:
        GenerateRunningError: If another generate or a load holds the lock.
    """
    with (output / LOCK_NAME).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GenerateRunningError(
                f"another generate or a load is running in {output}"
            ) from exc
        yield


def _remove_orphaned_work_dirs(output: Path) -> None:
    """Remove temp directories that a killed run left in output.

    A SIGKILL skips generate's cleanup. Only real directories whose name
    starts with the temp prefix are removed, never a symlink or a file.
    """
    for path in output.iterdir():
        if path.name.startswith(_WORK_PREFIX) and path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)


def _publish(work: Path, output: Path) -> None:
    """Move a finished run from work into output, with the stamp last.

    The old stamp is cleared first, so an output caught mid-move has no
    stamp and reads as stale. Known outputs that this run did not write are
    removed, so they cannot pass as current. Files outside OUTPUT_FILES are
    never touched.

    Raises:
        ValueError: If work holds a file outside OUTPUT_FILES.
    """
    written = {p.name for p in work.iterdir()} - {STAMP_NAME}
    if unknown := sorted(written - OUTPUT_FILES):
        raise ValueError(f"{', '.join(unknown)} must be added to OUTPUT_FILES")
    for name in sorted(written | {STAMP_NAME}):
        _fsync(work / name)
    clear_stamp(output)
    for name in sorted(OUTPUT_FILES - written):
        (output / name).unlink(missing_ok=True)
    for name in sorted(written):
        os.replace(work / name, output / name)
    # The CSV moves reach the disk before the stamp's move does.
    _fsync_dir(output)
    os.replace(work / STAMP_NAME, output / STAMP_NAME)
    _fsync_dir(output)


def _fsync_dir(path: Path) -> None:
    """Flush a directory's entries to disk, where the filesystem allows it.

    Some filesystems reject fsync on a directory with EINVAL. The moves then
    go to disk when that filesystem chooses, so only that error is ignored.
    """
    try:
        _fsync(path)
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise


def _fsync(path: Path) -> None:
    """Flush a file's or a directory's contents to disk.

    On macOS, os.fsync can leave the data in the drive's own cache, so
    F_FULLFSYNC is used where the platform has it. Some network and FUSE
    mounts reject F_FULLFSYNC, and those fall back to os.fsync, as SQLite
    does.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        if hasattr(fcntl, "F_FULLFSYNC"):
            try:
                fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            except OSError:
                os.fsync(fd)
        else:
            os.fsync(fd)
    finally:
        os.close(fd)


def _write_dataset(
    config: GeneratorConfig, work: Path, stamp: dict
) -> tuple[float, tuple[list[AircraftNode], int, list[dict], list[dict], list[dict]]]:
    """Write every CSV and the stamp into work.

    Returns:
        The elapsed seconds, and the values _print_summary reports.
    """
    aircraft, airports, days, seed = (
        config.n_aircraft,
        config.n_airports,
        config.n_days,
        config.seed,
    )

    rng = random.Random(seed)
    rng_np = np.random.default_rng(seed)

    t0 = time.time()
    console.print("\n[bold]Aircraft Digital Twin Generator[/bold]")
    console.print(
        f"  Aircraft: {aircraft}  |  Airports: {airports}  |  Days: {days}  |  Seed: {seed}"
    )
    console.print(f"  Output:   {config.output_dir.resolve()}\n")

    # ── 1. Fleet topology ───────────────────────────────────────────────────
    console.print("[cyan]Generating fleet topology…[/cyan]")
    fleet = generate_fleet(config)
    (
        aircraft_rows,
        system_rows,
        component_rows,
        sensor_rows,
        rels_ac_sys,
        rels_sys_comp,
        rels_sys_sens,
    ) = _fleet_rows(fleet)

    write_csv(aircraft_rows, work / "nodes_aircraft.csv")
    write_csv(system_rows, work / "nodes_systems.csv")
    write_csv(component_rows, work / "nodes_components.csv")
    write_csv(sensor_rows, work / "nodes_sensors.csv")
    write_csv(rels_ac_sys, work / "rels_aircraft_system.csv")
    write_csv(rels_sys_comp, work / "rels_system_component.csv")
    write_csv(rels_sys_sens, work / "rels_system_sensor.csv")
    console.print(
        f"  [green]✓[/green] {len(aircraft_rows)} aircraft  "
        f"{len(system_rows)} systems  "
        f"{len(component_rows)} components  "
        f"{len(sensor_rows)} sensors"
    )

    # ── 2. Sensor readings + maintenance events ─────────────────────────────
    console.print("[cyan]Generating sensor readings and maintenance events…[/cyan]")

    reading_fields = ["reading_id", "sensor_id", "ts", "value"]
    maintenance_rows: list[dict] = []
    event_counter = [0]
    total_readings = 0

    # Write readings incrementally per aircraft to keep memory bounded
    readings_path = work / "nodes_readings.csv"
    with readings_path.open("w", newline="", encoding="utf-8") as rf:
        import csv as _csv

        rw = _csv.DictWriter(rf, fieldnames=reading_fields)
        rw.writeheader()

        for ac_idx, ac in enumerate(fleet):
            system_series: dict[str, dict[str, np.ndarray]] = {}

            for system in ac.systems:
                series, rows = generate_system_readings(ac, system, config, rng_np)
                system_series[system.system_id] = series
                rw.writerows(rows)
                total_readings += len(rows)

            # Maintenance events for this aircraft
            ac_events = generate_maintenance_events(ac, system_series, config, event_counter, rng)
            maintenance_rows.extend(event.row for event in ac_events)

            if (ac_idx + 1) % 20 == 0 or ac_idx + 1 == len(fleet):
                console.print(
                    f"  [dim]{ac_idx + 1}/{len(fleet)} aircraft processed — "
                    f"{total_readings:,} readings, {len(maintenance_rows)} events so far[/dim]"
                )

    console.print(
        f"  [green]✓[/green] {total_readings:,} sensor readings  "
        f"{len(maintenance_rows)} maintenance events"
    )

    # Write maintenance nodes and relationships
    rels_comp_event: list[dict] = []
    rels_event_system: list[dict] = []
    rels_event_aircraft: list[dict] = []

    for evt in maintenance_rows:
        rels_comp_event.append(
            {
                ":START_ID(Component)": evt["component_id"],
                ":END_ID(MaintenanceEvent)": evt[":ID(MaintenanceEvent)"],
            }
        )
        rels_event_system.append(
            {
                ":START_ID(MaintenanceEvent)": evt[":ID(MaintenanceEvent)"],
                ":END_ID(System)": evt["system_id"],
            }
        )
        rels_event_aircraft.append(
            {
                ":START_ID(MaintenanceEvent)": evt[":ID(MaintenanceEvent)"],
                ":END_ID(Aircraft)": evt["aircraft_id"],
            }
        )

    write_csv(maintenance_rows, work / "nodes_maintenance.csv")
    write_csv(rels_comp_event, work / "rels_component_event.csv")
    write_csv(rels_event_system, work / "rels_event_system.csv")
    write_csv(rels_event_aircraft, work / "rels_event_aircraft.csv")

    # ── 3. Flight operations ────────────────────────────────────────────────
    console.print("[cyan]Generating flights, airports, and delays…[/cyan]")
    (
        airport_rows,
        flight_rows,
        delay_rows,
        rels_ac_flight,
        rels_dep,
        rels_arr,
        rels_delay,
    ) = generate_operations(fleet, config, rng)

    write_csv(airport_rows, work / "nodes_airports.csv")
    write_csv(flight_rows, work / "nodes_flights.csv")
    write_csv(delay_rows, work / "nodes_delays.csv")
    write_csv(rels_ac_flight, work / "rels_aircraft_flight.csv")
    write_csv(rels_dep, work / "rels_flight_departure.csv")
    write_csv(rels_arr, work / "rels_flight_arrival.csv")
    write_csv(rels_delay, work / "rels_flight_delay.csv")
    console.print(
        f"  [green]✓[/green] {len(airport_rows)} airports  "
        f"{len(flight_rows):,} flights  "
        f"{len(delay_rows):,} delays"
    )

    # ── 4. Component removals ───────────────────────────────────────────────
    console.print("[cyan]Generating component removals…[/cyan]")
    removal_rows, rels_ac_removal, rels_comp_removal = generate_removals(
        fleet, maintenance_rows, config, rng
    )
    write_csv(removal_rows, work / "nodes_removals.csv")
    write_csv(rels_ac_removal, work / "rels_aircraft_removal.csv")
    write_csv(rels_comp_removal, work / "rels_component_removal.csv")
    console.print(f"  [green]✓[/green] {len(removal_rows)} removals")

    write_stamp(work, stamp)

    summary = (fleet, total_readings, maintenance_rows, flight_rows, delay_rows)
    return time.time() - t0, summary


def _print_summary(
    config: GeneratorConfig,
    fleet: list[AircraftNode],
    n_readings: int,
    maintenance_rows: list[dict],
    flight_rows: list[dict],
    delay_rows: list[dict],
    elapsed: float,
) -> None:
    from collections import Counter

    console.print()
    table = Table(title="Generation Complete", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("Aircraft", str(len(fleet)))
    table.add_row("Systems", str(sum(len(ac.systems) for ac in fleet)))
    table.add_row("Components", str(sum(len(s.components) for ac in fleet for s in ac.systems)))
    table.add_row("Sensors", str(sum(len(s.sensors) for ac in fleet for s in ac.systems)))
    table.add_row("Sensor Readings", f"{n_readings:,}")
    table.add_row("Maintenance Events", str(len(maintenance_rows)))
    table.add_row("Airports", str(config.n_airports))
    table.add_row("Flights", f"{len(flight_rows):,}")
    table.add_row("Delays", f"{len(delay_rows):,}")

    console.print(table)

    # Per-model breakdown
    model_counts = Counter(ac.model for ac in fleet)
    console.print("\n[bold]Fleet composition:[/bold]")
    for model, count in sorted(model_counts.items()):
        console.print(f"  {model:<12} {count}")

    # Maintenance severity breakdown
    sev_counts = Counter(row["severity"] for row in maintenance_rows)
    console.print("\n[bold]Maintenance severity:[/bold]")
    for sev in EVENT_SEVERITIES:
        console.print(f"  {sev:<10} {sev_counts.get(sev, 0)}")

    # Degradation spread (operator breakdown)
    op_counts = Counter(ac.operator for ac in fleet)
    console.print("\n[bold]Aircraft by operator:[/bold]")
    for op, count in sorted(op_counts.items()):
        console.print(f"  {op:<14} {count}")

    m, s = divmod(int(elapsed), 60)
    elapsed_str = f"{m}m {s:02d}s" if m else f"{s}s"
    console.print(f"\n[green]Done in {elapsed_str}.[/green]")
    console.print(
        "[dim]GDS notes: cross-model kNN clusters are most visible with ≥80 aircraft. "
        "Louvain community count scales with n_aircraft × degradation variance.[/dim]\n"
    )


@app.command("render-manuals")
def render_manuals(
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 with a diff if a manual has drifted.")
    ] = False,
    manuals_dir: Annotated[
        Path, typer.Option("--manuals-dir", help="Directory holding the manuals.")
    ] = manuals.MANUALS_DIR,
) -> None:
    """Render the generated blocks of every maintenance manual from specs.

    Every manual renders before any is written, so a bad manual leaves them all
    as they were.
    """
    stats = manuals.load_stats(manuals_dir)
    pending: list[tuple[str, str, str]] = []
    for model, filename in manuals.MANUAL_FILES.items():
        text = (manuals_dir / filename).read_text(encoding="utf-8")
        try:
            rendered = manuals.render_text(text, model, stats)
        except manuals.ManualBlockError as exc:
            console.print(f"[red]{escape(filename)}: {escape(str(exc))}[/red]", soft_wrap=True)
            raise typer.Exit(1) from exc
        if rendered != text:
            pending.append((filename, text, rendered))
    for filename, text, rendered in pending:
        if check:
            diff = difflib.unified_diff(
                text.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"{filename} (committed)",
                tofile=f"{filename} (rendered)",
            )
            # Plain print: rich would read the diff's [brackets] as markup.
            print("".join(diff), end="")
            console.print(f"[red]{escape(filename)} has drifted[/red]")
        else:
            (manuals_dir / filename).write_text(rendered, encoding="utf-8")
            console.print(f"Rendered {escape(filename)}")
    if check and pending:
        console.print("Run `uv run generate-data render-manuals` to update them.")
        raise typer.Exit(1)
    if not pending:
        console.print(f"{len(manuals.MANUAL_FILES)} manuals in sync")


@app.command()
def stats(
    manuals_dir: Annotated[
        Path, typer.Option("--manuals-dir", help="Directory holding the manuals.")
    ] = manuals.MANUALS_DIR,
) -> None:
    """Count the default dataset's maintenance events for the manuals' statistics."""
    path = manuals_dir / manuals.STATS_NAME
    path.write_text(json.dumps(fleet_stats(), indent=2) + "\n", encoding="utf-8")
    console.print(
        f"Wrote {escape(str(path))} for {STATS_CONFIG.n_aircraft} aircraft over "
        f"{STATS_CONFIG.n_days} days, seed {STATS_CONFIG.seed}. "
        "Run `uv run generate-data render-manuals` to update the manuals."
    )


@app.command()
def validate(
    directory: Annotated[
        Path, typer.Argument(help="Directory containing generated CSV files.")
    ] = Path("."),
) -> None:
    """Check referential integrity of generated CSV files."""
    import csv as _csv

    console.print(f"\n[bold]Validating CSV files in:[/bold] {directory.resolve()}\n")

    errors: list[str] = []

    def load_ids(filename: str, id_col: str) -> set[str]:
        path = directory / filename
        if not path.exists():
            errors.append(f"Missing file: {filename}")
            return set()
        with path.open() as f:
            return {row[id_col] for row in _csv.DictReader(f)}

    def check_fk(filename: str, col: str, valid_ids: set[str], label: str) -> None:
        path = directory / filename
        if not path.exists():
            return
        with path.open() as f:
            for i, row in enumerate(_csv.DictReader(f), start=2):
                val = row.get(col)
                if val and val not in valid_ids:
                    errors.append(f"{filename}:{i} — {col}={val!r} not in {label}")

    aircraft_ids = load_ids("nodes_aircraft.csv", ":ID(Aircraft)")
    system_ids = load_ids("nodes_systems.csv", ":ID(System)")
    component_ids = load_ids("nodes_components.csv", ":ID(Component)")
    sensor_ids = load_ids("nodes_sensors.csv", ":ID(Sensor)")
    airport_ids = load_ids("nodes_airports.csv", ":ID(Airport)")
    flight_ids = load_ids("nodes_flights.csv", ":ID(Flight)")
    delay_ids = load_ids("nodes_delays.csv", ":ID(Delay)")
    event_ids = load_ids("nodes_maintenance.csv", ":ID(MaintenanceEvent)")

    check_fk("rels_aircraft_system.csv", ":START_ID(Aircraft)", aircraft_ids, "Aircraft")
    check_fk("rels_aircraft_system.csv", ":END_ID(System)", system_ids, "System")
    check_fk("rels_system_component.csv", ":START_ID(System)", system_ids, "System")
    check_fk("rels_system_component.csv", ":END_ID(Component)", component_ids, "Component")
    check_fk("rels_system_sensor.csv", ":START_ID(System)", system_ids, "System")
    check_fk("rels_system_sensor.csv", ":END_ID(Sensor)", sensor_ids, "Sensor")
    check_fk("rels_flight_departure.csv", ":END_ID(Airport)", airport_ids, "Airport")
    check_fk("rels_flight_arrival.csv", ":END_ID(Airport)", airport_ids, "Airport")
    check_fk("rels_flight_delay.csv", ":START_ID(Flight)", flight_ids, "Flight")
    check_fk("rels_flight_delay.csv", ":END_ID(Delay)", delay_ids, "Delay")
    check_fk("rels_component_event.csv", ":END_ID(MaintenanceEvent)", event_ids, "MaintenanceEvent")

    if errors:
        console.print(f"[red]Found {len(errors)} referential integrity error(s):[/red]")
        for e in errors[:20]:
            console.print(f"  [red]✗[/red] {e}")
        if len(errors) > 20:
            console.print(f"  [dim]… and {len(errors) - 20} more[/dim]")
        raise typer.Exit(1)
    else:
        console.print("[green]✓ All referential integrity checks passed.[/green]\n")


if __name__ == "__main__":
    app()
