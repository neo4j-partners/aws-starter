"""Static domain specifications: engine models, operators, airports, fault vocabulary."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum


class Direction(StrEnum):
    """Which way a sensor's value moves when something is wrong."""

    HIGH = "high"  # bad when the value rises, such as EGT
    LOW = "low"  # bad when the value falls, such as hydraulic pressure
    DEVIATION = "deviation"  # bad either way from baseline, such as N1


@dataclass(frozen=True)
class Bands:
    """Three thresholds, one per severity.

    HIGH and LOW sensors hold absolute values. DEVIATION sensors hold
    offsets from the baseline.
    """

    advisory: float  # crossing it gives MINOR
    caution: float  # crossing it gives MAJOR
    warning: float  # crossing it gives CRITICAL


@dataclass(frozen=True)
class FaultRoute:
    """A fault that a band crossing on one side can raise, and the parts it hits."""

    fault: str  # one of the CORRECTIVE_ACTIONS faults
    side: Direction  # HIGH or LOW: the side of the crossing that raises it
    components: tuple[str, ...]  # canonical component types it can hit
    weight: float  # pick weight when several routes match one side

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight):
            raise ValueError(f"fault route {self.fault!r}: weight {self.weight} is not finite")
        if self.weight < 0:
            raise ValueError(f"fault route {self.fault!r}: weight {self.weight} is negative")


@dataclass(frozen=True)
class SensorSpec:
    """One sensor type on one model: its unit, normal value, noise, drift, and bands."""

    type: str
    name: str
    unit: str
    baseline: float
    noise_std: float
    # Drift toward the bad side by the end of the window, as a share of the
    # baseline-to-warning gap, before the operator's degradation multiplier.
    # Each sensor draws one share from this range. The drift spreads evenly
    # over the window, so a longer window drifts more slowly, not further.
    drift_fraction: tuple[float, float]
    direction: Direction
    bands: Bands
    faults: tuple[FaultRoute, ...] = ()
    # Readings never go below this value, such as 0 for a disagreement.
    minimum: float | None = None

    def __post_init__(self) -> None:
        low, high = self.drift_fraction
        if not 0 <= low <= high:
            raise ValueError(f"sensor {self.type!r}: drift range {self.drift_fraction} is invalid")
        b = self.bands
        match self.direction:
            case Direction.HIGH:
                ordered = self.baseline < b.advisory < b.caution < b.warning
            case Direction.LOW:
                ordered = self.baseline > b.advisory > b.caution > b.warning
            case Direction.DEVIATION:
                ordered = 0 < b.advisory < b.caution < b.warning
        if not ordered:
            raise ValueError(
                f"sensor {self.type!r}: {self.direction} bands {b} are out of order "
                f"for baseline {self.baseline}"
            )
        sides = (
            {Direction.HIGH, Direction.LOW}
            if self.direction is Direction.DEVIATION
            else {self.direction}
        )
        for route in self.faults:
            if route.side not in sides:
                raise ValueError(
                    f"sensor {self.type!r}: route {route.fault!r} side {route.side} "
                    f"cannot trigger on a {self.direction} sensor"
                )
        # A crossing picks one of its side's routes by weight, so each side
        # with routes needs a positive total.
        for side in {route.side for route in self.faults}:
            total = sum(route.weight for route in self.faults if route.side is side)
            if total <= 0:
                raise ValueError(
                    f"sensor {self.type!r}: {side} route weights sum to {total:g}; "
                    "at least one must be positive"
                )

    def offsets(self) -> tuple[float, float, float]:
        """Advisory, caution, and warning as distances from baseline toward the bad side."""
        b = self.bands
        match self.direction:
            case Direction.HIGH:
                return (
                    b.advisory - self.baseline,
                    b.caution - self.baseline,
                    b.warning - self.baseline,
                )
            case Direction.LOW:
                return (
                    self.baseline - b.advisory,
                    self.baseline - b.caution,
                    self.baseline - b.warning,
                )
            case Direction.DEVIATION:
                return (b.advisory, b.caution, b.warning)


# The vibration levels every manual's Vibration Limits table uses, in band
# order. Advisory, Caution, and Warning start at a sensor's three bands.
VIBRATION_LEVELS: tuple[str, str, str, str] = ("Normal", "Advisory", "Caution", "Warning")


# The engine power settings of every manual's Normal Operating Parameters
# table, in column order. The renderer adds a cruise column from the specs.
PHASES: tuple[str, str, str, str] = (
    "Ground Idle",
    "Flight Idle",
    "Max Continuous",
    "Takeoff (5 min)",
)


@dataclass(frozen=True)
class EgtBand:
    """One row of a manual's turbine operating limits, in °C."""

    normal_below: float
    caution_to: float
    maximum: float


@dataclass(frozen=True)
class EgtLimits:
    """Instantaneous EGT limits, as the FADEC monitors them.

    These are a different scale from the hourly EGT trend readings.
    """

    ground_idle: str
    flight_idle: str
    max_continuous: EgtBand
    takeoff: EgtBand
    start_max: float | None


@dataclass(frozen=True)
class EngineSpec:
    engine_type: str
    sensors: tuple[SensorSpec, ...]
    egt_limits: EgtLimits
    # Row label -> one cell per PHASES entry, for the rows the generator does
    # not produce. The renderer builds the EGT and vibration rows from specs.
    phase_limits: dict[str, tuple[str, str, str, str]]


def _engine_sensors(
    egt: tuple[float, float, float, float],
    egt_noise_std: float,
    egt_drift: tuple[float, float],
    vib: tuple[float, float, float, float],
    vib_noise_std: float,
    vib_drift: tuple[float, float],
    n1_cruise: float,
    fuel_cruise: float,
) -> tuple[SensorSpec, ...]:
    """Build one model's four engine sensors.

    egt and vib are (baseline, advisory, caution, warning). N1 bands are
    2, 4, and 6 % from cruise N1. Fuel flow bands are 8, 15, and 25 % of
    cruise fuel flow.
    """
    return (
        SensorSpec(
            "EGT",
            "Exhaust Gas Temperature",
            "°C",
            baseline=egt[0],
            noise_std=egt_noise_std,
            drift_fraction=egt_drift,
            direction=Direction.HIGH,
            bands=Bands(*egt[1:]),
            faults=(FaultRoute("Overheat", Direction.HIGH, ("HP Turbine",), 1.0),),
        ),
        SensorSpec(
            "Vibration",
            "Engine Vibration",
            "ips",
            baseline=vib[0],
            noise_std=vib_noise_std,
            drift_fraction=vib_drift,
            direction=Direction.HIGH,
            bands=Bands(*vib[1:]),
            faults=(
                FaultRoute(
                    "Bearing wear", Direction.HIGH, ("Thrust Bearing", "Reduction Gearbox"), 0.55
                ),
                FaultRoute("Vibration exceedance", Direction.HIGH, ("Fan Module",), 0.45),
            ),
        ),
        SensorSpec(
            "N1Speed",
            "Fan Speed N1",
            "%",
            baseline=n1_cruise,
            noise_std=0.5,
            drift_fraction=(0.0, 0.0),
            direction=Direction.DEVIATION,
            bands=Bands(2.0, 4.0, 6.0),
            # The N1 pickup sits at the fan.
            faults=tuple(
                FaultRoute("Sensor drift", side, ("Fan Module",), 1.0)
                for side in (Direction.HIGH, Direction.LOW)
            ),
        ),
        SensorSpec(
            "FuelFlow",
            "Fuel Flow",
            "kg/s",
            baseline=fuel_cruise,
            noise_std=round(0.02 * fuel_cruise, 4),
            drift_fraction=(0.0, 0.0),
            direction=Direction.DEVIATION,
            bands=Bands(*(fuel_cruise * share for share in (0.08, 0.15, 0.25))),
            faults=(
                FaultRoute("Fuel starvation", Direction.LOW, ("Main Fuel Pump",), 0.6),
                FaultRoute("Contamination", Direction.LOW, ("Main Fuel Pump",), 0.4),
                FaultRoute("Leak", Direction.HIGH, ("Main Fuel Pump",), 1.0),
            ),
        ),
    )


# Engine bands come from each manual's own limits. The current EGT warning
# value is the caution value. Vibration noise scales with the gap from
# baseline to caution. EGT and vibration drift tops are 0.66 of the warning
# gap, so the most degraded operator (1.5x) ends the window within 1% of
# warning (0.66 x 1.5 = 0.99).
ENGINE_SPECS: dict[str, EngineSpec] = {
    "B737-800": EngineSpec(
        engine_type="CFM56-7B",
        sensors=_engine_sensors(
            egt=(658.0, 678.0, 688.0, 698.0),
            egt_noise_std=3.5,
            egt_drift=(0.095, 0.66),
            vib=(0.8, 2.0, 3.5, 4.5),
            vib_noise_std=0.135,
            vib_drift=(0.149, 0.66),
            n1_cruise=88.0,
            fuel_cruise=0.36,
        ),
        egt_limits=EgtLimits(
            ground_idle="350-420",
            flight_idle="420-480",
            max_continuous=EgtBand(895, 925, 925),
            takeoff=EgtBand(930, 950, 950),
            start_max=725,
        ),
        phase_limits={
            "N1Speed (%)": ("20-25", "25-30", "95", "104"),
            "N2 (%)": ("55-62", "62-68", "95", "101"),
            "FuelFlow (kg/s)": ("0.10-0.18", "0.18-0.25", "0.85-1.10", "1.20-1.50"),
            "Oil Pressure (psi)": ("35-60", "40-70", "45-75", "45-75"),
            "Oil Temperature (°C)": ("50-90", "60-120", "80-140", "80-155"),
        },
    ),
    "A320-200": EngineSpec(
        engine_type="V2500-A1",
        sensors=_engine_sensors(
            egt=(560.0, 580.0, 590.0, 600.0),
            egt_noise_std=3.0,
            egt_drift=(0.061, 0.66),
            vib=(0.8, 2.0, 3.5, 5.0),
            vib_noise_std=0.12,
            vib_drift=(0.136, 0.66),
            n1_cruise=87.0,
            fuel_cruise=0.34,
        ),
        egt_limits=EgtLimits(
            ground_idle="380",
            flight_idle="450",
            max_continuous=EgtBand(620, 650, 665),
            takeoff=EgtBand(650, 680, 695),
            start_max=None,
        ),
        phase_limits={
            "N1Speed (%)": ("22", "28", "97", "104"),
            "N2 (%)": ("58", "65", "97", "102"),
            # The max continuous cell is interpolated between the idle and
            # takeoff ranges, not taken from a source.
            "FuelFlow (kg/s)": ("0.15-0.25", "0.15-0.25", "0.85-1.20", "1.20-1.95"),
            "Oil Pressure (psi)": ("25-55", "40-65", "40-65", "40-65"),
            "Oil Temperature (°C)": ("40-90", "60-120", "60-150", "60-155"),
        },
    ),
    "A321neo": EngineSpec(
        engine_type="LEAP-1A",
        sensors=_engine_sensors(
            egt=(634.0, 654.0, 664.0, 674.0),
            egt_noise_std=2.8,
            egt_drift=(0.067, 0.66),
            vib=(0.7, 2.0, 3.0, 4.0),
            vib_noise_std=0.095,
            vib_drift=(0.111, 0.66),
            n1_cruise=86.0,
            fuel_cruise=0.38,
        ),
        egt_limits=EgtLimits(
            ground_idle="320-400",
            flight_idle="400-480",
            max_continuous=EgtBand(950, 980, 1000),
            takeoff=EgtBand(1000, 1040, 1060),
            start_max=750,
        ),
        phase_limits={
            "N1Speed (%)": ("18-23", "23-28", "92", "97"),
            "N2 (%)": ("52-58", "58-64", "96", "100"),
            "FuelFlow (kg/s)": ("0.12-0.20", "0.20-0.30", "0.95-1.25", "1.50-2.00"),
            "Oil Pressure (psi)": ("40-65", "45-75", "50-80", "50-85"),
            "Oil Temperature (°C)": ("45-85", "55-115", "75-135", "75-150"),
        },
    ),
    "E190": EngineSpec(
        engine_type="CF34-10E",
        sensors=_engine_sensors(
            egt=(641.0, 661.0, 671.0, 681.0),
            egt_noise_std=3.2,
            egt_drift=(0.103, 0.66),
            vib=(0.8, 2.0, 3.0, 4.0),
            vib_noise_std=0.10,
            vib_drift=(0.127, 0.66),
            n1_cruise=87.0,
            fuel_cruise=0.27,
        ),
        egt_limits=EgtLimits(
            ground_idle="330-400",
            flight_idle="400-460",
            max_continuous=EgtBand(840, 870, 870),
            takeoff=EgtBand(870, 895, 900),
            start_max=730,
        ),
        phase_limits={
            "N1Speed (%)": ("22-28", "28-35", "96", "100"),
            "FuelFlow (kg/s)": ("0.08-0.15", "0.15-0.22", "0.75-0.95", "1.00-1.20"),
            "Oil Pressure (psi)": ("35-60", "40-70", "45-75", "45-75"),
            "Oil Temperature (°C)": ("50-90", "60-120", "80-140", "80-155"),
        },
    ),
    "A220-300": EngineSpec(
        engine_type="PW1500G",
        sensors=_engine_sensors(
            egt=(625.0, 645.0, 655.0, 665.0),
            egt_noise_std=2.5,
            egt_drift=(0.074, 0.66),
            vib=(0.6, 1.5, 2.5, 3.5),
            vib_noise_std=0.08,
            vib_drift=(0.131, 0.66),
            n1_cruise=85.0,
            fuel_cruise=0.28,
        ),
        egt_limits=EgtLimits(
            ground_idle="310-380",
            flight_idle="380-440",
            max_continuous=EgtBand(820, 855, 855),
            takeoff=EgtBand(855, 880, 890),
            start_max=700,
        ),
        phase_limits={
            "N1Speed (%)": ("18-24", "24-30", "92", "100"),
            "FuelFlow (kg/s)": ("0.09-0.16", "0.16-0.24", "0.80-1.10", "1.15-1.35"),
            "Oil Pressure (psi)": ("35-60", "40-70", "45-75", "45-75"),
            "Oil Temperature (°C)": ("50-90", "60-120", "80-140", "80-155"),
            "Gearbox Oil Pressure (psi)": ("50-65", "55-70", "65-80", "65-80"),
            "Gearbox Oil Temperature (°C)": ("60-90", "70-110", "90-130", "90-130"),
        },
    ),
}

_HYDRAULICS_SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec(
        "HydPressure",
        "Hydraulic Pressure",
        "psi",
        baseline=3000.0,
        noise_std=20.0,
        drift_fraction=(0.0, 0.15),
        direction=Direction.LOW,
        bands=Bands(2800.0, 2600.0, 2400.0),
        faults=(
            FaultRoute("Leak", Direction.LOW, ("Hydraulic Pump",), 0.6),
            FaultRoute("Contamination", Direction.LOW, ("Hydraulic Pump",), 0.4),
        ),
    ),
    SensorSpec(
        "HydQuantity",
        "Hydraulic Fluid Quantity",
        "%",
        baseline=90.0,
        noise_std=0.5,
        drift_fraction=(0.0, 0.27),
        direction=Direction.LOW,
        bands=Bands(70.0, 60.0, 50.0),
        faults=(
            FaultRoute(
                "Leak", Direction.LOW, ("Hydraulic Reservoir", "Flight Control Actuator"), 1.0
            ),
        ),
    ),
)

_AVIONICS_SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec(
        "BusVoltage",
        "DC Bus Voltage",
        "V DC",
        baseline=28.0,
        noise_std=0.15,
        drift_fraction=(0.0, 0.09),
        direction=Direction.LOW,
        bands=Bands(26.0, 25.0, 24.0),
        faults=(
            FaultRoute(
                "Electrical fault",
                Direction.LOW,
                ("Flight Management System", "Air Data Unit", "Navigation Receiver"),
                1.0,
            ),
        ),
    ),
    SensorSpec(
        "AirDataDisagree",
        "Air Data Airspeed Disagreement",
        "kt",
        baseline=0.5,
        noise_std=0.15,
        drift_fraction=(0.0, 0.096),
        direction=Direction.HIGH,
        bands=Bands(3.0, 5.0, 8.0),
        faults=(FaultRoute("Sensor drift", Direction.HIGH, ("Air Data Unit",), 1.0),),
        minimum=0.0,
    ),
)


def _a321neo_hydraulics() -> tuple[SensorSpec, ...]:
    """The A321neo manual's normal pressure band is 2,900 to 3,100 psi."""
    pressure, quantity = _HYDRAULICS_SENSORS
    return (replace(pressure, bands=replace(pressure.bands, advisory=2900.0)), quantity)


# Sensors on each system type, per model. Key order is the system order.
SYSTEM_SENSORS: dict[str, dict[str, tuple[SensorSpec, ...]]] = {
    "Engine": {model: spec.sensors for model, spec in ENGINE_SPECS.items()},
    "Avionics": dict.fromkeys(ENGINE_SPECS, _AVIONICS_SENSORS),
    "Hydraulics": {
        model: _a321neo_hydraulics() if model == "A321neo" else _HYDRAULICS_SENSORS
        for model in ENGINE_SPECS
    },
}


def sensors_for(system_type: str, model: str) -> tuple[SensorSpec, ...]:
    """Return the sensors on one system type of one model, in sensor id order."""
    return SYSTEM_SENSORS.get(system_type, {}).get(model, ())


# Model allocation for aircraft beyond the manual registry. Proportions must
# sum to 1.0. The first 30 aircraft are the registry in MANUAL_FLEET_TAILS,
# so the 30-aircraft default follows the registry shape instead: E190 is 10
# of 30, and every other model is 5 of 30.
MODEL_DISTRIBUTION: list[tuple[str, float]] = [
    ("B737-800", 0.35),
    ("A320-200", 0.25),
    ("A321neo", 0.20),
    ("E190", 0.10),
    ("A220-300", 0.10),
]

# Tail numbers on each manual's **Fleet** line. The generator gives these to
# the first aircraft, so every manual tail exists in the generated data.
# tests/test_manual_registry.py checks them against the manuals. The key
# order sets the round-robin order of the registry aircraft.
MANUAL_FLEET_TAILS: dict[str, list[str]] = {
    "B737-800": ["N95040A", "N53032E", "N84110I", "N26760M", "N44342Q"],
    "A320-200": ["N30268B", "N81338F", "N32276J", "N76758N", "N63098R"],
    "A321neo": ["N54980C", "N86057G", "N89365K", "N65164O", "N96107S"],
    "E190": [
        "N10002",
        "N10017",
        "N10023",
        "N10036",
        "N10050",
        "N10068",
        "N10071",
        "N10073",
        "N10084",
        "N10096",
    ],
    "A220-300": ["N20001", "N20002", "N20003", "N20004", "N20005"],
}

# Operator of each manual tail, from the Registrations column of each
# manual's fleet table. The A220-300 manual has no such table, and its
# **Operator:** line names ExampleAir for all five aircraft. The test in
# tests/test_manual_registry.py checks these against the manuals. Aircraft
# beyond the registry get shuffled operators instead.
MANUAL_TAIL_OPERATORS: dict[str, str] = {
    # B737-800
    "N95040A": "ExampleAir",
    "N53032E": "ExampleAir",
    "N84110I": "SkyWays",
    "N26760M": "RegionalCo",
    "N44342Q": "NorthernJet",
    # A320-200
    "N30268B": "SkyWays",
    "N81338F": "SkyWays",
    "N32276J": "ExampleAir",
    "N76758N": "RegionalCo",
    "N63098R": "NorthernJet",
    # A321neo
    "N54980C": "RegionalCo",
    "N86057G": "RegionalCo",
    "N89365K": "ExampleAir",
    "N65164O": "SkyWays",
    "N96107S": "NorthernJet",
    # E190
    "N10002": "ExampleAir",
    "N10017": "ExampleAir",
    "N10023": "ExampleAir",
    "N10036": "SkyWays",
    "N10050": "SkyWays",
    "N10068": "SkyWays",
    "N10071": "RegionalCo",
    "N10073": "RegionalCo",
    "N10084": "NorthernJet",
    "N10096": "NorthernJet",
    # A220-300
    "N20001": "ExampleAir",
    "N20002": "ExampleAir",
    "N20003": "ExampleAir",
    "N20004": "ExampleAir",
    "N20005": "ExampleAir",
}


@dataclass(frozen=True)
class Utilization:
    """How hard each aircraft flies.

    Each aircraft draws its hours per cycle from its model's value with
    +/- cycle_jitter. It then flies a whole number of legs a day, drawn so
    the day's hours fall in hours_per_day. Flights, airframe hours, and
    cycles all follow those draws.
    """

    hours_per_day: tuple[float, float]
    hours_per_cycle: dict[str, float]
    cycle_jitter: float


# Typical short-haul stage lengths: the E190 flies the shortest legs and the
# A321neo the longest.
UTILIZATION = Utilization(
    hours_per_day=(8.0, 10.0),
    hours_per_cycle={
        "B737-800": 1.9,
        "A320-200": 1.8,
        "A321neo": 2.2,
        "E190": 1.4,
        "A220-300": 1.6,
    },
    cycle_jitter=0.10,
)


# Entry-into-service range for each model, first and last day inclusive.
# B737, A320, and E190 come from "entered service between" in each manual's
# §1.2 Fleet Configuration, and A321neo from its §1.3. The A220 manual gives
# a month per tail instead, so its range spans that table. Every aircraft
# without a manual date gets a day in its model's range.
ENTRY_INTO_SERVICE_RANGES: dict[str, tuple[date, date]] = {
    "B737-800": (date(2016, 1, 1), date(2022, 12, 31)),
    "A320-200": (date(2017, 1, 1), date(2023, 12, 31)),
    "A321neo": (date(2020, 1, 1), date(2023, 12, 31)),
    "E190": (date(2018, 1, 1), date(2022, 12, 31)),
    "A220-300": (date(2022, 3, 1), date(2023, 5, 31)),
}

# Entry into service from the A220 manual's §1.2 Fleet Configuration table,
# the first of each listed month. tests/test_manual_registry.py checks these
# against the manual.
MANUAL_TAIL_ENTRY_INTO_SERVICE: dict[str, date] = {
    "N20001": date(2022, 3, 1),
    "N20002": date(2022, 6, 1),
    "N20003": date(2022, 10, 1),
    "N20004": date(2023, 2, 1),
    "N20005": date(2023, 5, 1),
}

MANUFACTURER: dict[str, str] = {
    "B737-800": "Boeing",
    "A320-200": "Airbus",
    "A321neo": "Airbus",
    "E190": "Embraer",
    "A220-300": "Airbus",
}


@dataclass(frozen=True)
class OperatorProfile:
    name: str
    # Multiplies degradation slopes — 1.0 is average, >1.0 means worse maintenance quality
    degradation_multiplier: float
    # Baseline probability that any given flight incurs a delay
    delay_rate: float


OPERATORS: list[OperatorProfile] = [
    OperatorProfile("ExampleAir", degradation_multiplier=1.00, delay_rate=0.35),
    OperatorProfile("SkyWays", degradation_multiplier=0.75, delay_rate=0.25),
    OperatorProfile("RegionalCo", degradation_multiplier=1.50, delay_rate=0.50),
    OperatorProfile("NorthernJet", degradation_multiplier=1.20, delay_rate=0.40),
]


@dataclass(frozen=True)
class AirportSpec:
    airport_id: str
    name: str
    city: str
    country: str
    iata: str
    icao: str
    lat: float
    lon: float
    is_hub: bool  # hubs get more routes and higher flight frequency


AIRPORTS: list[AirportSpec] = [
    AirportSpec(
        "AP001",
        "John F. Kennedy International Airport",
        "New York",
        "USA",
        "JFK",
        "KJFK",
        40.6413,
        -73.7781,
        True,
    ),
    AirportSpec(
        "AP002",
        "Los Angeles International Airport",
        "Los Angeles",
        "USA",
        "LAX",
        "KLAX",
        33.9416,
        -118.4085,
        True,
    ),
    AirportSpec(
        "AP003",
        "O'Hare International Airport",
        "Chicago",
        "USA",
        "ORD",
        "KORD",
        41.9742,
        -87.9073,
        True,
    ),
    AirportSpec(
        "AP004",
        "Dallas/Fort Worth International Airport",
        "Dallas",
        "USA",
        "DFW",
        "KDFW",
        32.8998,
        -97.0403,
        True,
    ),
    AirportSpec(
        "AP005",
        "Hartsfield–Jackson Atlanta International",
        "Atlanta",
        "USA",
        "ATL",
        "KATL",
        33.6407,
        -84.4277,
        True,
    ),
    AirportSpec(
        "AP006",
        "Denver International Airport",
        "Denver",
        "USA",
        "DEN",
        "KDEN",
        39.8561,
        -104.6737,
        True,
    ),
    AirportSpec(
        "AP007",
        "San Francisco International Airport",
        "San Francisco",
        "USA",
        "SFO",
        "KSFO",
        37.6213,
        -122.3790,
        True,
    ),
    AirportSpec(
        "AP008",
        "Seattle-Tacoma International Airport",
        "Seattle",
        "USA",
        "SEA",
        "KSEA",
        47.4502,
        -122.3088,
        True,
    ),
    AirportSpec(
        "AP009",
        "Miami International Airport",
        "Miami",
        "USA",
        "MIA",
        "KMIA",
        25.7959,
        -80.2870,
        True,
    ),
    AirportSpec(
        "AP010",
        "Boston Logan International Airport",
        "Boston",
        "USA",
        "BOS",
        "KBOS",
        42.3656,
        -71.0096,
        True,
    ),
    AirportSpec(
        "AP011",
        "Phoenix Sky Harbor International Airport",
        "Phoenix",
        "USA",
        "PHX",
        "KPHX",
        33.4373,
        -112.0078,
        False,
    ),
    AirportSpec(
        "AP012",
        "Minneapolis–Saint Paul International Airport",
        "Minneapolis",
        "USA",
        "MSP",
        "KMSP",
        44.8820,
        -93.2218,
        False,
    ),
    AirportSpec(
        "AP013",
        "Detroit Metropolitan Wayne County Airport",
        "Detroit",
        "USA",
        "DTW",
        "KDTW",
        42.2162,
        -83.3554,
        False,
    ),
    AirportSpec(
        "AP014",
        "Portland International Airport",
        "Portland",
        "USA",
        "PDX",
        "KPDX",
        45.5898,
        -122.5951,
        False,
    ),
    AirportSpec(
        "AP015",
        "Salt Lake City International Airport",
        "Salt Lake City",
        "USA",
        "SLC",
        "KSLC",
        40.7884,
        -111.9778,
        False,
    ),
    AirportSpec(
        "AP016",
        "Philadelphia International Airport",
        "Philadelphia",
        "USA",
        "PHL",
        "KPHL",
        39.8719,
        -75.2411,
        False,
    ),
    AirportSpec(
        "AP017",
        "Tampa International Airport",
        "Tampa",
        "USA",
        "TPA",
        "KTPA",
        27.9755,
        -82.5332,
        False,
    ),
    AirportSpec(
        "AP018",
        "Charlotte Douglas International Airport",
        "Charlotte",
        "USA",
        "CLT",
        "KCLT",
        35.2141,
        -80.9431,
        False,
    ),
    AirportSpec(
        "AP019",
        "Las Vegas Harry Reid International Airport",
        "Las Vegas",
        "USA",
        "LAS",
        "KLAS",
        36.0840,
        -115.1537,
        False,
    ),
    AirportSpec(
        "AP020",
        "Houston George Bush Intercontinental Airport",
        "Houston",
        "USA",
        "IAH",
        "KIAH",
        29.9902,
        -95.3368,
        False,
    ),
    AirportSpec(
        "AP021",
        "Washington Dulles International Airport",
        "Washington DC",
        "USA",
        "IAD",
        "KIAD",
        38.9445,
        -77.4558,
        False,
    ),
    AirportSpec(
        "AP022",
        "Ronald Reagan Washington National Airport",
        "Arlington",
        "USA",
        "DCA",
        "KDCA",
        38.8512,
        -77.0402,
        False,
    ),
    AirportSpec(
        "AP023",
        "San Diego International Airport",
        "San Diego",
        "USA",
        "SAN",
        "KSAN",
        32.7338,
        -117.1933,
        False,
    ),
    AirportSpec(
        "AP024",
        "Baltimore Washington International Airport",
        "Baltimore",
        "USA",
        "BWI",
        "KBWI",
        39.1754,
        -76.6683,
        False,
    ),
    AirportSpec(
        "AP025",
        "Austin-Bergstrom International Airport",
        "Austin",
        "USA",
        "AUS",
        "KAUS",
        30.1975,
        -97.6664,
        False,
    ),
    AirportSpec(
        "AP026",
        "Nashville International Airport",
        "Nashville",
        "USA",
        "BNA",
        "KBNA",
        36.1245,
        -86.6782,
        False,
    ),
    AirportSpec(
        "AP027",
        "Raleigh-Durham International Airport",
        "Raleigh",
        "USA",
        "RDU",
        "KRDU",
        35.8776,
        -78.7875,
        False,
    ),
    AirportSpec(
        "AP028",
        "Kansas City International Airport",
        "Kansas City",
        "USA",
        "MCI",
        "KMCI",
        39.2976,
        -94.7139,
        False,
    ),
    AirportSpec(
        "AP029",
        "New Orleans Louis Armstrong International",
        "New Orleans",
        "USA",
        "MSY",
        "KMSY",
        29.9934,
        -90.2580,
        False,
    ),
    AirportSpec(
        "AP030",
        "Cleveland Hopkins International Airport",
        "Cleveland",
        "USA",
        "CLE",
        "KCLE",
        41.4117,
        -81.8498,
        False,
    ),
    AirportSpec(
        "AP031",
        "Indianapolis International Airport",
        "Indianapolis",
        "USA",
        "IND",
        "KIND",
        39.7173,
        -86.2944,
        False,
    ),
    AirportSpec(
        "AP032",
        "Pittsburgh International Airport",
        "Pittsburgh",
        "USA",
        "PIT",
        "KPIT",
        40.4915,
        -80.2329,
        False,
    ),
    AirportSpec(
        "AP033",
        "St. Louis Lambert International Airport",
        "St. Louis",
        "USA",
        "STL",
        "KSTL",
        38.7487,
        -90.3700,
        False,
    ),
    AirportSpec(
        "AP034",
        "San Jose International Airport",
        "San Jose",
        "USA",
        "SJC",
        "KSJC",
        37.3626,
        -121.9290,
        False,
    ),
    AirportSpec(
        "AP035",
        "Sacramento International Airport",
        "Sacramento",
        "USA",
        "SMF",
        "KSMF",
        38.6954,
        -121.5908,
        False,
    ),
    AirportSpec(
        "AP036",
        "Honolulu Daniel K. Inouye International",
        "Honolulu",
        "USA",
        "HNL",
        "PHNL",
        21.3187,
        -157.9224,
        False,
    ),
    AirportSpec(
        "AP037",
        "Memphis International Airport",
        "Memphis",
        "USA",
        "MEM",
        "KMEM",
        35.0424,
        -89.9767,
        False,
    ),
    AirportSpec(
        "AP038",
        "Jacksonville International Airport",
        "Jacksonville",
        "USA",
        "JAX",
        "KJAX",
        30.4941,
        -81.6879,
        False,
    ),
    AirportSpec(
        "AP039",
        "Milwaukee Mitchell International Airport",
        "Milwaukee",
        "USA",
        "MKE",
        "KMKE",
        42.9472,
        -87.8966,
        False,
    ),
    AirportSpec(
        "AP040",
        "Albuquerque International Sunport",
        "Albuquerque",
        "USA",
        "ABQ",
        "KABQ",
        35.0402,
        -106.6090,
        False,
    ),
]


# Every fleet sensor type once, as (type, name, unit), in system order.
SENSOR_TYPES: list[tuple[str, str, str]] = list(
    dict.fromkeys(
        (sensor.type, sensor.name, sensor.unit)
        for by_model in SYSTEM_SENSORS.values()
        for sensors in by_model.values()
        for sensor in sensors
    )
)


@dataclass(frozen=True)
class DelayCauseSpec:
    """A flight delay cause, its share of delays, and its duration range."""

    cause: str
    weight: float
    min_minutes: int
    max_minutes: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight):
            raise ValueError(f"delay cause {self.cause!r}: weight {self.weight} is not finite")
        if self.weight < 0:
            raise ValueError(f"delay cause {self.cause!r}: weight {self.weight} is negative")
        if self.min_minutes < 0 or self.max_minutes < 0:
            raise ValueError(
                f"delay cause {self.cause!r}: minutes {self.min_minutes} to "
                f"{self.max_minutes} include a negative"
            )
        if self.min_minutes > self.max_minutes:
            raise ValueError(
                f"delay cause {self.cause!r}: min_minutes {self.min_minutes} "
                f"is above max_minutes {self.max_minutes}"
            )


def _positive_weight_sum(specs: tuple[DelayCauseSpec, ...]) -> tuple[DelayCauseSpec, ...]:
    """Return specs unchanged, or raise if their weights cannot drive a weighted draw."""
    if (total := sum(spec.weight for spec in specs)) <= 0:
        raise ValueError(f"delay cause weights sum to {total:g}; at least one must be positive")
    return specs


# Flight delay causes, each with its weight and duration range in minutes.
DELAY_CAUSE_SPECS: tuple[DelayCauseSpec, ...] = _positive_weight_sum(
    (
        DelayCauseSpec("Weather", 0.30, 20, 180),
        DelayCauseSpec("Maintenance", 0.25, 30, 240),
        DelayCauseSpec("NAS", 0.25, 15, 90),
        DelayCauseSpec("Carrier", 0.20, 10, 60),
    )
)
DELAY_CAUSES: tuple[str, ...] = tuple(spec.cause for spec in DELAY_CAUSE_SPECS)

# Maintenance event severities, most severe first.
EVENT_SEVERITIES: tuple[str, ...] = ("CRITICAL", "MAJOR", "MINOR")

# One corrective action per fault. The sensor fault routes use these faults.
CORRECTIVE_ACTIONS: dict[str, str] = {
    "Overheat": "Inspected hot section; replaced affected turbine stage and seals",
    "Vibration exceedance": "Balanced rotating assembly; replaced damper pads and inspected bearings",
    "Bearing wear": "Replaced bearing assembly; flushed and refilled lubrication system",
    "Fuel starvation": "Cleaned fuel manifold; replaced fuel control unit and high-pressure pump",
    "Contamination": "Flushed system; replaced filter elements and recalibrated sensors",
    "Sensor drift": "Replaced sensor unit and recalibrated engine monitoring system",
    "Leak": "Located and sealed leak source; pressure-tested and cleared for service",
    "Electrical fault": "Replaced faulty wiring harness and connector block; re-ran BITE check",
}


@dataclass(frozen=True)
class FaultCode:
    """One code in the manuals' fault code reference, the same on every model.

    A generated code records a fault the generator raises, so the manuals
    derive its severities from the routes. A manual-only code names a fault
    the generator never raises, and keeps the severities the manuals give it.
    """

    code: str
    system: str  # the system type it applies to
    fault: str  # the CORRECTIVE_ACTIONS fault; the description for a manual-only code
    generated: bool = True
    severities: tuple[str, ...] = ()  # manual-only codes only, worst first

    def __post_init__(self) -> None:
        if self.generated and self.severities:
            raise ValueError(
                f"fault code {self.code!r}: a generated code takes its severities from the routes"
            )
        if not self.generated and not self.severities:
            raise ValueError(f"fault code {self.code!r}: a manual-only code needs severities")


# The fault code reference in section 7 of every manual, in table order. The
# numbering is the B737 manual's.
FAULT_CODES: tuple[FaultCode, ...] = (
    FaultCode("ENG-SDR-001", "Engine", "Sensor drift"),
    FaultCode("ENG-CNT-002", "Engine", "Contamination"),
    FaultCode("ENG-BRG-003", "Engine", "Bearing wear"),
    FaultCode("ENG-LEAK-004", "Engine", "Leak"),
    FaultCode("ENG-VIB-005", "Engine", "Vibration exceedance"),
    FaultCode("ENG-OVH-006", "Engine", "Overheat"),
    FaultCode("ENG-FUEL-007", "Engine", "Fuel starvation"),
    FaultCode(
        "ENG-ELF-008",
        "Engine",
        "Electrical Fault",
        generated=False,
        severities=("CRITICAL", "MAJOR", "MINOR"),
    ),
    FaultCode("AVN-SDR-001", "Avionics", "Sensor drift"),
    FaultCode("AVN-ELF-002", "Avionics", "Electrical fault"),
    FaultCode("AVN-FMS-003", "Avionics", "FMS Malfunction", generated=False, severities=("MAJOR",)),
    FaultCode(
        "AVN-NAV-004", "Avionics", "NAV Receiver Fault", generated=False, severities=("MINOR",)
    ),
    FaultCode("HYD-LEAK-001", "Hydraulics", "Leak"),
    FaultCode("HYD-CNT-002", "Hydraulics", "Contamination"),
    FaultCode(
        "HYD-PRS-003",
        "Hydraulics",
        "Low Pressure",
        generated=False,
        severities=("CRITICAL", "MAJOR"),
    ),
    FaultCode("HYD-QTY-004", "Hydraulics", "Low Quantity", generated=False, severities=("MAJOR",)),
)


@dataclass(frozen=True)
class ComponentSpec:
    """One component type, with the part name each manual uses for it.

    type is the canonical name: the Component type in the graph, and the
    value the extraction prompt and the cross-link join use.
    """

    type: str
    # The part name on every model, unless names gives one for the model.
    # Empty means the type.
    name: str = ""
    names: dict[str, str] = field(default_factory=dict)
    # The models that have this component. None means every model.
    models: frozenset[str] | None = None
    # Other names the manuals use for this part. The cross-link join accepts
    # them, but the extraction prompt does not list them, to keep it short.
    link_aliases: tuple[str, ...] = ()

    def name_for(self, model: str) -> str:
        """Return the manual's part name for this component on model."""
        return self.names.get(model, self.name or self.type)

    def fits(self, model: str) -> bool:
        """Return True if model has this component."""
        return self.models is None or model in self.models

    def aliases(self) -> list[str]:
        """Return the type and every manual name, in order, without repeats."""
        candidates = [self.type, self.name or self.type, *self.names.values()]
        return list(dict.fromkeys(candidates))


_BOEING_AIRBUS = ("B737-800", "A320-200", "A321neo")
_A220_E190 = ("A220-300", "E190")

# Components by system type, in id order: C01 is first. C01 to C05 keep one
# order on every model, so a component id names the same type on each.
# Names come from each manual's component sections.
COMPONENTS_BY_SYSTEM: dict[str, tuple[ComponentSpec, ...]] = {
    "Engine": (
        ComponentSpec("Fan Module", names={"A321neo": "Fan Module (Carbon Fiber Composite)"}),
        ComponentSpec("HP Compressor", name="Compressor Stage (High-Pressure)"),
        ComponentSpec("HP Turbine", name="High-Pressure Turbine"),
        ComponentSpec("Main Fuel Pump"),
        ComponentSpec("Thrust Bearing", name="Thrust Bearing Assembly"),
        # The PW1500G is a geared turbofan.
        ComponentSpec("Reduction Gearbox", models=frozenset({"A220-300"})),
    ),
    "Avionics": (
        ComponentSpec(
            "Flight Management System",
            name="FMS",
            link_aliases=("Flight Management Computer", "FMC"),
        ),
        ComponentSpec(
            "Air Data Unit",
            names=dict.fromkeys(_BOEING_AIRBUS, "ADC") | dict.fromkeys(_A220_E190, "ADIRU"),
            link_aliases=(
                "Air Data Computer",
                "Air Data and Inertial Reference Unit",
                "Air Data / Inertial Reference Unit",
                "Air Data Inertial Reference Unit",
            ),
        ),
        ComponentSpec(
            "Navigation Receiver",
            names=dict.fromkeys(_BOEING_AIRBUS, "NAV") | dict.fromkeys(_A220_E190, "MMR"),
            link_aliases=("Multi-Mode Receiver",),
        ),
    ),
    "Hydraulics": (
        ComponentSpec(
            "Hydraulic Pump",
            name="Main Hydraulic Pump",
            names={"E190": "Engine-Driven Pump"},
            link_aliases=("EDP",),
        ),
        ComponentSpec("Hydraulic Reservoir"),
        ComponentSpec(
            "Flight Control Actuator",
            name="Flap Actuator Assembly",
            names={"A220-300": "Electrohydraulic Servo Actuators"},
            link_aliases=("EHSA", "Electrohydraulic Servo Actuator", "Flap Actuator"),
        ),
    ),
}

COMPONENT_TYPES_BY_SYSTEM: dict[str, list[str]] = {
    system: [spec.type for spec in specs] for system, specs in COMPONENTS_BY_SYSTEM.items()
}


def component_aliases(components_by_system: dict[str, tuple[ComponentSpec, ...]]) -> dict[str, str]:
    """Return lowercase alias -> canonical component type.

    Each type, each of its manual names, and each link-only alias is an
    alias. Raises ValueError if an alias, ignoring case, names two types.
    """
    aliases: dict[str, str] = {}
    for specs in components_by_system.values():
        for spec in specs:
            for alias in (*spec.aliases(), *spec.link_aliases):
                key = alias.lower()
                if aliases.get(key, spec.type) != spec.type:
                    raise ValueError(
                        f"alias {key!r} names both {aliases[key]!r} and {spec.type!r}; "
                        "an alias must name one component type"
                    )
                aliases[key] = spec.type
    return aliases


COMPONENT_ALIASES = component_aliases(COMPONENTS_BY_SYSTEM)
