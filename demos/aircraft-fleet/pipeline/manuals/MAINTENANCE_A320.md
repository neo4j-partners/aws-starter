# A320-200 Maintenance and Troubleshooting Manual

**Document Number:** AMM-A320-2024-001
**Revision:** 1.0
**Effective Date:** October 1, 2024
**Applicability:** A320-200 series aircraft equipped with IAE V2500-A1 engines
**Operator:** SkyWays, ExampleAir, RegionalCo, NorthernJet
**Fleet:** N30268B, N81338F, N32276J, N76758N, N63098R

---

## Document Control

| Rev | Date | Description | Author |
|-----|------|-------------|--------|
| 1.0 | 2024-10-01 | Initial Release | Engineering Division |
| 0.9 | 2024-09-15 | Draft for review | Maintenance Planning |

**NOTICE:** This manual contains proprietary information. Maintenance procedures must be performed by certified personnel only. Always refer to the latest revision of Airbus AMM documentation for authoritative guidance.

---

## Table of Contents

1. [Aircraft Overview](#1-aircraft-overview)
2. [System Architecture](#2-system-architecture)
3. [Engine System - V2500-A1](#3-engine-system---v2500-a1)
4. [Engine Troubleshooting Procedures](#4-engine-troubleshooting-procedures)
5. [Avionics System](#5-avionics-system)
6. [Hydraulics System](#6-hydraulics-system)
7. [Fault Code Reference](#7-fault-code-reference)
8. [Troubleshooting Decision Trees](#8-troubleshooting-decision-trees)
9. [Scheduled Maintenance Tasks](#9-scheduled-maintenance-tasks)
10. [Appendices](#10-appendices)

---

## 1. Aircraft Overview

### 1.1 General Specifications

| Parameter | Value |
|-----------|-------|
| Aircraft Type | Airbus A320-200 |
| Powerplant | 2x IAE V2500-A1 Turbofan |
| Maximum Takeoff Weight (MTOW) | 77,000 kg (169,756 lb) |
| Maximum Landing Weight (MLW) | 66,000 kg (145,505 lb) |
| Maximum Zero Fuel Weight (MZFW) | 62,500 kg (137,789 lb) |
| Fuel Capacity | 24,210 liters (6,396 US gal) |
| Range | 6,100 km (3,300 nm) |
| Service Ceiling | 39,800 ft |

### 1.2 Fleet Configuration

The A320-200 fleet operates across four partner carriers configured for medium-haul operations.

| Operator | Registrations | Primary Routes |
|----------|---------------|----------------|
| ExampleAir | N32276J | Domestic medium-haul |
| SkyWays | N30268B, N81338F | Domestic medium-haul |
| RegionalCo | N76758N | Mixed domestic/regional |
| NorthernJet | N63098R | Domestic medium-haul |

Aircraft entered service between 2017 and 2023, configured in a single-class or dual-class layout for 150–180 passengers.

### 1.3 ATA Chapter Reference

This manual covers the following ATA chapters:

| ATA Chapter | System | Reference Section |
|-------------|--------|-------------------|
| ATA 29 | Hydraulic Power | Section 6 |
| ATA 34 | Navigation | Section 5 |
| ATA 71 | Powerplant | Sections 3-4 |
| ATA 72 | Engine | Sections 3-4 |
| ATA 73 | Engine Fuel and Control | Section 3 |
| ATA 77 | Engine Indicating | Section 3 |

---

## 2. System Architecture

### 2.1 Major System Groups

Each A320-200 aircraft comprises four primary monitored system groups:

<!-- BEGIN GENERATED: component-tree -->
```
AIRCRAFT (A320-200)
│
├── ENGINE SYSTEM #1 (V2500-A1 Left)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── ENGINE SYSTEM #2 (V2500-A1 Right)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── AVIONICS SYSTEM
│   ├── Flight Management System (FMS)
│   ├── Air Data Computer (ADC)
│   └── Navigation Receiver (NAV)
│
└── HYDRAULICS SYSTEM
    ├── Main Hydraulic Pump
    ├── Hydraulic Reservoir
    └── Flap Actuator Assembly
```
<!-- END GENERATED: component-tree -->

#### 2.1.1 Engine Systems (V2500-A1)

The A320-200 is powered by two International Aero Engines (IAE) V2500-A1 high-bypass turbofan engines, mounted in underwing nacelles. Each engine produces 25,000 lbf of thrust and operates independently with full redundancy. The V2500 features a two-spool design with a single-stage fan, 4-stage low-pressure compressor, 10-stage high-pressure compressor, annular combustor, 2-stage high-pressure turbine, and 5-stage low-pressure turbine. Engine health is continuously monitored via four dedicated sensors per engine measuring exhaust gas temperature (EGT), vibration levels, fan speed (N1), and fuel flow rate.

<!-- BEGIN GENERATED: system-shares-engine -->
In the generated fleet data, engine systems account for 21 of the A320-200's 36 maintenance events, or 58%. The most common engine faults are overheat with 7 events, vibration exceedance with 7, and sensor drift with 4.
<!-- END GENERATED: system-shares-engine -->

**ATA Reference:** Chapters 71 (Powerplant), 72 (Engine), 73 (Engine Fuel and Control), 77 (Engine Indicating)

#### 2.1.2 Avionics System

The avionics system provides flight management, navigation, and air data computation functions essential for safe aircraft operation. The system is built around dual Flight Management Systems (FMS) that handle flight planning, navigation computation, performance optimization, and guidance commands. Three Air Data Computers (ADC) provide redundant altitude, airspeed, and Mach number calculations using pitot-static inputs. The Navigation Receiver integrates VOR, ILS localizer, glideslope, and marker beacon reception for precision approaches. All avionics components communicate via ARINC 429 digital data buses with built-in test equipment (BITE) for fault detection.

<!-- BEGIN GENERATED: system-shares-avionics -->
In the generated fleet data, avionics accounts for 6 of the A320-200's 36 maintenance events, or 17%. The avionics faults are sensor drift with 4 events and electrical fault with 2.
<!-- END GENERATED: system-shares-avionics -->

Avionics faults are often resolved through software patches or calibration adjustments.

**ATA Reference:** Chapter 34 (Navigation)

#### 2.1.3 Hydraulics System

The A320-200 hydraulic system provides power for flight control surfaces, landing gear operation, brakes, thrust reversers, and cargo doors. The aircraft employs three independent hydraulic systems designated Green, Blue, and Yellow, each operating at 3,000 psi. This manual focuses on the Green system, which is powered by an engine-driven pump on Engine #1. The system includes a main hydraulic pump capable of 26 gpm flow rate, a 14.5-liter reservoir with integrated quantity indication, and multiple actuators including the flap actuator assembly for high-lift device operation. Hydraulic fluid (Skydrol LD-4) requires regular monitoring for contamination and proper fluid levels.

<!-- BEGIN GENERATED: system-shares-hydraulics -->
In the generated fleet data, the hydraulics system accounts for 9 of the A320-200's 36 maintenance events, or 25%. The hydraulics faults are leak with 7 events and contamination with 2.
<!-- END GENERATED: system-shares-hydraulics -->

**ATA Reference:** Chapter 29 (Hydraulic Power)

### 2.2 Engine Health Monitoring

<!-- BEGIN GENERATED: sensor-table -->
Each V2500-A1 engine carries four monitoring sensors. The Avionics and Hydraulics systems carry two sensors each. The digital twin records every sensor hourly.

| System | Sensor Type | Parameter | Unit | Location |
|--------|-------------|-----------|------|----------|
| Engine | EGT | Exhaust Gas Temperature | °C | Turbine exhaust |
| Engine | Vibration | Engine Vibration | ips | Fan case |
| Engine | N1Speed | Fan Speed N1 | % | Fan shaft |
| Engine | FuelFlow | Fuel Flow | kg/s | Fuel metering unit |
| Avionics | BusVoltage | DC Bus Voltage | V DC | DC essential bus |
| Avionics | AirDataDisagree | Air Data Airspeed Disagreement | kt | Captain and first officer air data sources |
| Hydraulics | HydPressure | Hydraulic Pressure | psi | System pressure manifold |
| Hydraulics | HydQuantity | Hydraulic Fluid Quantity | % | Hydraulic reservoir |
<!-- END GENERATED: sensor-table -->

**Sensor Sampling Rate:** Continuous (1 Hz during flight, recorded hourly for trend analysis)

<!-- BEGIN GENERATED: egt-trend-note -->
**Digital Twin Monitoring Note:** The Digital Twin Monitoring System records hourly trend-averaged EGT values on a normalized scale calibrated for long-term degradation detection. For the V2500-A1, the trend baseline is 560°C, with Advisory at 580°C, Caution at 590°C, and Warning at 600°C. These trend values differ from the instantaneous EGT limits in the Normal Operating Parameters table and Appendix 10.1, which reflect peak values during takeoff and high-power operations. The trend scale detects gradual EGT margin deterioration over weeks and months, not acute exceedances. The absolute limits in this manual refer to instantaneous FADEC-monitored readings.
<!-- END GENERATED: egt-trend-note -->

### 2.3 Component Identification Schema

Components are identified using the following nomenclature:

<!-- BEGIN GENERATED: component-ids -->
```
[Aircraft ID]-[System]-[Component]

Example: AC1002-S01-C03
         │       │    └── Component: High-Pressure Turbine
         │       └─────── System: Engine #1
         └─────────────── Aircraft: AC1002 (N30268B)
```

**System Codes:**
- S01: Engine #1 (Left)
- S02: Engine #2 (Right)
- S03: Avionics
- S04: Hydraulics
<!-- END GENERATED: component-ids -->

---

## 3. Engine System - V2500-A1

### 3.1 Engine Specifications

| Parameter | Value |
|-----------|-------|
| Manufacturer | International Aero Engines (IAE) |
| Model | V2500-A1 |
| Type | Two-spool turbofan |
| Thrust Rating | 25,000 lbf (111 kN) |
| Bypass Ratio | 5.4:1 |
| Overall Pressure Ratio | 30:1 |
| Dry Weight | 2,359 kg (5,200 lb) |

### 3.2 Component Descriptions

#### 3.2.1 Fan Module
**Part Number:** V25-FM-2100
**ATA Reference:** 72-21

The fan module consists of a single-stage fan with 22 wide-chord titanium blades. The fan provides approximately 80% of total engine thrust.

**Inspection Intervals:**
- Visual inspection: Every 500 flight hours
- Borescope inspection: Every 2,500 flight hours
- Overhaul: On-condition (typically 15,000-20,000 cycles)

#### 3.2.2 Compressor Stage (High-Pressure)
**Part Number:** V25-HPC-3400
**ATA Reference:** 72-34

The 10-stage high-pressure compressor (HPC) achieves a pressure ratio of approximately 10:1. Variable stator vanes in stages 1-4 provide surge protection during transient operations.

**Common Fault Modes:**
- Compressor stall (vibration exceedance)
- Blade erosion (performance degradation)
- Variable vane actuator malfunction (sensor drift)

#### 3.2.3 High-Pressure Turbine
**Part Number:** V25-HPT-4200
**ATA Reference:** 72-42

The two-stage HPT extracts energy to drive the HPC. Turbine blades feature advanced cooling passages and thermal barrier coatings.

**Operating Limits:**
<!-- BEGIN GENERATED: egt-limits -->
| Parameter | Normal | Caution | Maximum |
|-----------|--------|---------|---------|
| EGT (Takeoff, 5 min) | < 650°C | 650-695°C | 695°C |
| EGT (Max Continuous) | < 620°C | 620-665°C | 665°C |
<!-- END GENERATED: egt-limits -->

#### 3.2.4 Main Fuel Pump
**Part Number:** V25-FP-7310
**ATA Reference:** 73-10

The engine-driven fuel pump provides metered fuel flow to the combustion chamber. The pump incorporates an integral fuel filter and fuel-oil heat exchanger.

<!-- BEGIN GENERATED: fuel-flow-range -->
**Flow Rate:** 0.15 - 1.95 kg/s (ground idle to takeoff)
<!-- END GENERATED: fuel-flow-range -->

**Warning Signs of Degradation:**
- Fluctuating fuel flow readings
- Increased fuel filter differential pressure
- Abnormal pump vibration

#### 3.2.5 Thrust Bearing Assembly
**Part Number:** V25-TB-7250
**ATA Reference:** 72-50

The thrust bearing assembly absorbs axial loads from the high-pressure rotor system. Ball bearing design with oil jet lubrication.

**Replacement Criteria:**
- Oil debris analysis exceeding limits
- Bearing temperature rise > 15°C above baseline
- Audible bearing noise during ground run

### 3.3 Normal Operating Parameters

<!-- BEGIN GENERATED: normal-parameters -->
| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) | Max Continuous | Takeoff (5 min) |
|-----------|-------------|-------------|-----------------------|----------------|-----------------|
| N1Speed (%) | 22 | 28 | 87 (85-89) | 97 | 104 |
| N2 (%) | 58 | 65 | — | 97 | 102 |
| EGT (°C) | 380 | 450 | 560 (< 580) | < 620 | < 650 |
| FuelFlow (kg/s) | 0.15-0.25 | 0.15-0.25 | 0.34 (0.31-0.37) | 0.85-1.20 | 1.20-1.95 |
| Oil Pressure (psi) | 25-55 | 40-65 | — | 40-65 | 40-65 |
| Oil Temperature (°C) | 40-90 | 60-120 | — | 60-150 | 60-155 |
| Vibration N1 (ips) | < 2.0 | < 2.0 | 0.8 (< 2.0) | < 2.0 | < 2.0 |
<!-- END GENERATED: normal-parameters -->

---

## 4. Engine Troubleshooting Procedures

### 4.1 Overheat Condition (EGT Exceedance)

**Fault Code:** ENG-OVH-006
**Severity Classification:** CRITICAL / MAJOR / MINOR (based on temperature and duration)
<!-- BEGIN GENERATED: fault-stats-engine-overheat -->
**Fleet Statistics:** In the generated fleet data, overheat accounts for 7 of the A320-200's 21 engine maintenance events, or 33%.
<!-- END GENERATED: fault-stats-engine-overheat -->

#### Symptoms
- EGT indication above normal operating range
- ECAM caution/warning message
- Possible visible heat damage on borescope inspection

#### Immediate Actions
1. Reduce thrust to idle if flight conditions permit
2. Monitor EGT trend for stabilization
3. If EGT exceeds the takeoff maximum in the Operating Limits table, initiate engine shutdown procedures per QRH

#### Troubleshooting Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Review DFDR/QAR data for EGT exceedance duration | Document peak temperature and exposure time |
| 2 | Perform visual inspection of exhaust nozzle | Check for discoloration or distortion |
| 3 | Borescope inspection of HPT blades | Check for thermal distress, coating loss |
| 4 | Verify EGT probe calibration | Compare dual probe readings (< 5°C variance) |
| 5 | Check fuel nozzle spray pattern | Ensure even fuel distribution |

#### Corrective Actions by Severity

**CRITICAL (EGT above the takeoff maximum, or more than 5 minutes in the takeoff caution band):**
- Ground aircraft pending HPT borescope inspection
- If blade damage found: Engine removal for shop visit
- Estimated downtime: 5-10 days

**MAJOR (EGT in the takeoff caution band, intermittent):**
- Perform hot section inspection within 50 flight hours
- Replace EGT probes if calibration drift detected
- Monitor trend data for recurrence

**MINOR (EGT trending high but within limits):**
- Adjust engine trim if applicable
- Schedule inspection at next C-check
- Continue monitoring with increased frequency

### 4.2 Vibration Exceedance

**Fault Code:** ENG-VIB-005
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-vibration-exceedance -->
**Fleet Statistics:** In the generated fleet data, vibration exceedance accounts for 7 of the A320-200's 21 engine maintenance events, or 33%.
<!-- END GENERATED: fault-stats-engine-vibration-exceedance -->

#### Vibration Limits

<!-- BEGIN GENERATED: vibration-bands -->
| Level | N1 Vibration | Event Severity | Flight Deck Alert |
|-------|--------------|----------------|-------------------|
| Normal | < 2.0 ips | None | None |
| Advisory | 2.0-3.5 ips | MINOR | ENG 1(2) VIB (amber) |
| Caution | 3.5-5.0 ips | MAJOR | ENG 1(2) VIB HI (amber) |
| Warning | ≥ 5.0 ips | CRITICAL | ENG 1(2) VIB (red) |
<!-- END GENERATED: vibration-bands -->

#### Troubleshooting Procedure

| Step | Action | Diagnostic Indicator |
|------|--------|---------------------|
| 1 | Identify vibration frequency spectrum | Isolate rotor source (N1 vs N2) |
| 2 | Check fan blade condition | FOD damage, ice accretion, blade loss |
| 3 | Inspect spinner and nosecone | Balance weights, attachment |
| 4 | Review oil debris analysis | Bearing wear indication |
| 5 | Perform fan blade balance check | Correct imbalance if identified |

#### Common Root Causes
- Fan blade damage from FOD
- Bearing wear in thrust bearing assembly
- Compressor blade erosion
- Sensor malfunction / cable damage

### 4.3 Fuel Starvation

**Fault Code:** ENG-FUEL-007
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-fuel-starvation -->
**Fleet Statistics:** In the generated fleet data, fuel starvation accounts for 0 of the A320-200's 21 engine maintenance events, or 0%.
<!-- END GENERATED: fault-stats-engine-fuel-starvation -->

#### Symptoms
- Fuel flow fluctuation or sudden drop
- Engine rollback or flameout
- Fuel filter bypass indication

#### Immediate Actions
1. Check fuel quantity and crossfeed configuration
2. Select alternate fuel pump if available
3. If flameout occurs, initiate relight procedure per QRH

#### Troubleshooting Procedure

| Step | Action | Check Point |
|------|--------|-------------|
| 1 | Verify fuel tank quantity | Ensure adequate fuel and no fuel imbalance |
| 2 | Check fuel filter differential pressure | Replace if > 15 psi differential |
| 3 | Inspect fuel pump delivery pressure | Nominal: 800-1200 psi |
| 4 | Check fuel metering unit operation | Verify proper scheduling |
| 5 | Inspect fuel lines for leaks or blockage | Visual and pressure decay test |

### 4.4 Bearing Wear

**Fault Code:** ENG-BRG-003
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-bearing-wear -->
**Fleet Statistics:** In the generated fleet data, bearing wear accounts for 3 of the A320-200's 21 engine maintenance events, or 14%.
<!-- END GENERATED: fault-stats-engine-bearing-wear -->

#### Detection Methods
- Oil debris monitoring (chip detectors, spectrographic analysis)
- Vibration trend analysis
- Oil consumption monitoring
- Temperature rise in bearing compartment

#### Oil Analysis Limits

| Metal | Normal (ppm) | Caution (ppm) | Action (ppm) |
|-------|--------------|---------------|--------------|
| Iron (Fe) | < 5 | 5-15 | > 15 |
| Chromium (Cr) | < 2 | 2-5 | > 5 |
| Nickel (Ni) | < 3 | 3-8 | > 8 |
| Silver (Ag) | < 1 | 1-3 | > 3 |

#### Corrective Actions
- **CRITICAL:** Immediate engine removal; bearing replacement at shop
- **MAJOR:** Schedule engine removal within 100 flight hours
- **MINOR:** Increase oil sampling frequency to every 50 hours; trend monitoring

### 4.5 Sensor Drift

**Fault Code:** ENG-SDR-001
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-sensor-drift -->
**Fleet Statistics:** In the generated fleet data, sensor drift accounts for 4 of the A320-200's 21 engine maintenance events, or 19%.
<!-- END GENERATED: fault-stats-engine-sensor-drift -->

#### Symptoms
- Parameter disagree messages on ECAM
- Gradual deviation between redundant sensor readings
- Thrust asymmetry indications
- FADEC fault messages

#### Diagnostic Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Review the FADEC fault log | Identify affected channel and parameter |
| 2 | Compare sensor values (Channel A vs B) | Determine which channel has drifted |
| 3 | Cross-check with independent references | Validate actual engine condition |
| 4 | Perform sensor Built-In Test (BIT) | Confirm sensor hardware status |
| 5 | Check wiring continuity and connections | Rule out intermittent connections |

#### Corrective Actions by Severity

**CRITICAL (Drift > 10% affecting thrust control):**
- Ground aircraft pending sensor replacement
- Replace affected sensor or EEC channel
- Perform engine ground run verification

**MAJOR (Drift 5-10%, redundancy compromised):**
- Dispatch with MEL if applicable
- Schedule sensor replacement within 10 days
- Increase monitoring frequency

**MINOR (Drift < 5%, trending):**
- Document in aircraft log
- Schedule calibration check at next maintenance visit
- Continue trend monitoring

### 4.6 Contamination

**Fault Code:** ENG-CNT-002
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-contamination -->
**Fleet Statistics:** In the generated fleet data, contamination accounts for 0 of the A320-200's 21 engine maintenance events, or 0%.
<!-- END GENERATED: fault-stats-engine-contamination -->

#### Types of Contamination

| Type | Source | Detection Method |
|------|--------|------------------|
| Oil contamination | Bearing seal leak, oil cooler failure | Oil analysis, carbon deposits |
| Fuel contamination | Water, particulates, microbial growth | Fuel filter DP, fuel sample |
| Compressor fouling | Airborne particles, salt, volcanic ash | EGT margin loss, performance |
| Turbine deposits | Combustion byproducts, sulfidation | Borescope, EGT spread |

#### Diagnostic Procedure

| Step | Action | Indicator |
|------|--------|-----------|
| 1 | Review trend data for EGT margin degradation | A steady EGT rise indicates fouling |
| 2 | Perform oil spectrographic analysis | Check for wear metals, contamination |
| 3 | Check fuel filter differential pressure | High DP indicates fuel contamination |
| 4 | Borescope HPT nozzle and blades | Visual deposits, coating loss |
| 5 | Perform compressor wash if applicable | Evaluate EGT margin recovery |

#### Corrective Actions

**CRITICAL (Severe contamination affecting operation):**
- Engine removal for shop cleaning
- HPT blade replacement if sulfidation present
- Oil system flush and filter replacement

**MAJOR (Moderate contamination):**
- Perform on-wing compressor wash (motoring wash)
- Replace fuel filter element
- Enhanced oil sampling (every 25 FH)
- Monitor EGT margin recovery

**MINOR (Early detection):**
- Schedule compressor wash at next opportunity
- Increase fuel sampling frequency
- Document trend for fleet analysis

### 4.7 Leak Detection

**Fault Code:** ENG-LEAK-004
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-leak -->
**Fleet Statistics:** In the generated fleet data, leak accounts for 0 of the A320-200's 21 engine maintenance events, or 0%.
<!-- END GENERATED: fault-stats-engine-leak -->

#### Leak Classification

| Class | Rate | Definition | Action |
|-------|------|------------|--------|
| A | Seep | Wetness, no drip | Monitor, clean |
| B | Leak | 1-5 drops/min | Repair within 100 FH |
| C | Heavy | > 5 drops/min | Repair before flight |

#### Common Leak Sources

| System | Location | Visual Indicator |
|--------|----------|------------------|
| Oil | Accessory gearbox | Brown/black streaks |
| Oil | Turbine rear bearing | Oil in exhaust area |
| Fuel | Fuel manifold | Fuel odor, staining |
| Fuel | Fuel metering unit connections | Wet fittings |
| Bleed | Duct connections | Sooting, heat damage |

#### Troubleshooting Procedure

| Step | Action | Inspection Point |
|------|--------|------------------|
| 1 | Perform visual inspection of engine | Note all fluid trails |
| 2 | Clean suspected areas thoroughly | Prepare for leak check |
| 3 | Operate engine at ground idle | Observe for fresh leaks |
| 4 | Apply leak detection solution | Bubble test for pneumatic |
| 5 | UV dye inspection (if oil dye installed) | Pinpoint oil leak source |

---

## 5. Avionics System

### 5.1 System Overview

The A320-200 avionics suite provides flight management, navigation, and air data functions integrated through the ARINC 429 digital data bus.

### 5.2 Component Descriptions

#### 5.2.1 Flight Management System (FMS)
**Part Number:** AVN-FMS-3401
**ATA Reference:** 34-01

The dual FMS units provide:
- Flight planning and navigation
- Performance optimization
- Automated guidance commands
- ACARS datalink interface

**Common Faults:**
- Database corruption (requires reload)
- Navigation sensor input failures
- Display unit anomalies

#### 5.2.2 Air Data Computer (ADC)
**Part Number:** AVN-ADC-3402
**ATA Reference:** 34-02

Three ADCs provide:
- Altitude computation
- Airspeed calculation
- Mach number derivation
- Total air temperature

**Calibration Requirements:**
- Leak test: Every 24 months
- Accuracy verification: Every 12 months

#### 5.2.3 Navigation Receiver (NAV)
**Part Number:** AVN-NAV-3403
**ATA Reference:** 34-03

Integrated VOR/ILS receiver providing:
- VOR bearing information
- Localizer guidance
- Glideslope guidance
- Marker beacon reception

### 5.3 Avionics Troubleshooting

#### 5.3.1 Sensor Drift

**Fault Code:** AVN-SDR-001
<!-- BEGIN GENERATED: fault-stats-avionics-sensor-drift -->
**Fleet Statistics:** In the generated fleet data, sensor drift accounts for 4 of the A320-200's 6 avionics maintenance events, or 67%.
<!-- END GENERATED: fault-stats-avionics-sensor-drift -->

Sensor drift manifests as gradual deviation between redundant sensor inputs or comparison with known references.

**Diagnostic Steps:**
1. Compare ADC outputs (ADC1 vs ADC2 vs ADC3)
2. Cross-check with GPS-derived parameters
3. Review BITE (Built-In Test Equipment) fault logs
4. Perform sensor calibration verification

**Corrective Actions:**
- Software recalibration if within tolerance
- ADC replacement if drift exceeds 2% of full scale
- Wiring inspection for intermittent connections

#### 5.3.2 Electrical Fault

**Fault Code:** AVN-ELF-002
<!-- BEGIN GENERATED: fault-stats-avionics-electrical-fault -->
**Fleet Statistics:** In the generated fleet data, electrical fault accounts for 2 of the A320-200's 6 avionics maintenance events, or 33%.
<!-- END GENERATED: fault-stats-avionics-electrical-fault -->

**Common Causes:**
- Power supply irregularities
- Ground faults
- Connector corrosion
- Wire chafing

**Isolation Procedure:**
1. Check circuit breaker status
2. Measure bus voltage at LRU
3. Inspect connectors for damage/corrosion
4. Perform continuity test on suspect wiring
5. Apply software patch if fault is software-related

---

## 6. Hydraulics System

### 6.1 System Overview

The A320-200 hydraulic system operates at 3,000 psi and comprises three independent systems (Green, Blue, Yellow). This section focuses on the Green system components.

### 6.2 Component Descriptions

#### 6.2.1 Main Hydraulic Pump
**Part Number:** HYD-PUMP-2901
**ATA Reference:** 29-01

Engine-driven pump specifications:
- Operating pressure: 3,000 psi
- Flow rate: 26 gpm (at 3,000 psi)
- Case drain flow: < 3 gpm

#### 6.2.2 Hydraulic Reservoir
**Part Number:** HYD-RES-2902
**ATA Reference:** 29-02

- Capacity: 14.5 liters (Green system)
- Operating temperature: -54°C to +135°C
- Fluid type: Skydrol LD-4 or equivalent

#### 6.2.3 Flap Actuator Assembly
**Part Number:** HYD-FLAP-2903
**ATA Reference:** 29-03

Linear hydraulic actuator providing:
- Flap extension/retraction
- Position feedback to SFCC
- Load limiting protection

### 6.3 Hydraulics Troubleshooting

#### 6.3.1 Leak Detection

**Fault Code:** HYD-LEAK-001
<!-- BEGIN GENERATED: fault-stats-hydraulics-leak -->
**Fleet Statistics:** In the generated fleet data, leak accounts for 7 of the A320-200's 9 hydraulics maintenance events, or 78%.
<!-- END GENERATED: fault-stats-hydraulics-leak -->

**Inspection Points:**
| Location | Access Panel | Common Leak Source |
|----------|--------------|-------------------|
| Pump area | 161VU | Pump seal, case drain |
| Reservoir | 162VU | Filler cap, sight glass |
| Actuators | Wing panels | Rod seals, fittings |
| Lines | Various | B-nut connections |

**Leak Classification:**
- Class A (Seep): < 1 drop/minute - Monitor
- Class B (Leak): 1-5 drops/minute - Repair within 10 days
- Class C (Heavy): > 5 drops/minute - Repair before flight

#### 6.3.2 Contamination

**Fault Code:** HYD-CNT-002
<!-- BEGIN GENERATED: fault-stats-hydraulics-contamination -->
**Fleet Statistics:** In the generated fleet data, contamination accounts for 2 of the A320-200's 9 hydraulics maintenance events, or 22%.
<!-- END GENERATED: fault-stats-hydraulics-contamination -->

**Contamination Sources:**
- Water ingress (humidity, rain)
- Particulate matter (wear debris, external)
- Chemical contamination (wrong fluid type)

**Testing Procedure:**
1. Obtain fluid sample from reservoir drain
2. Perform particle count analysis (NAS 1638 Class 6 max)
3. Check water content (< 0.1% by volume)
4. Verify fluid acidity (TAN < 1.5)

**Corrective Actions:**
- Flush and filter if particle count elevated
- Replace fluid if water or chemical contamination
- Inspect and clean reservoir if debris source identified

---

## 7. Fault Code Reference

### 7.1 Engine Fault Codes

<!-- BEGIN GENERATED: fault-codes-engine -->
| Code | Description | Severity | ATA | Primary Action |
|------|-------------|----------|-----|----------------|
| ENG-SDR-001 | Sensor Drift | CRIT/MAJ/MIN | 77 | Identify sensor, verify, replace |
| ENG-CNT-002 | Contamination | CRIT/MAJ/MIN | 72 | Oil/fuel analysis, wash/clean |
| ENG-BRG-003 | Bearing Wear | CRIT/MAJ/MIN | 72 | Oil analysis, vibration check |
| ENG-LEAK-004 | Fluid Leak | CRIT/MAJ/MIN | 79 | Identify source, repair |
| ENG-VIB-005 | Vibration Exceedance | CRIT/MAJ/MIN | 72 | Fan balance, bearing check |
| ENG-OVH-006 | Overheat | CRIT/MAJ/MIN | 72 | Reduce thrust, borescope |
| ENG-FUEL-007 | Fuel Starvation | CRIT/MAJ/MIN | 73 | Check fuel system, filter |
| ENG-ELF-008 | Electrical Fault | CRIT/MAJ/MIN | 77 | FADEC diagnostics, wiring |
<!-- END GENERATED: fault-codes-engine -->

### 7.2 Avionics Fault Codes

<!-- BEGIN GENERATED: fault-codes-avionics -->
| Code | Description | Severity | ATA | Primary Action |
|------|-------------|----------|-----|----------------|
| AVN-SDR-001 | Sensor Drift | CRIT/MAJ/MIN | 34 | ADC comparison, calibration |
| AVN-ELF-002 | Electrical Fault | CRIT/MAJ/MIN | 34 | Power check, connector inspect |
| AVN-FMS-003 | FMS Malfunction | MAJ | 34 | Reset, database reload |
| AVN-NAV-004 | NAV Receiver Fault | MIN | 34 | Antenna check, LRU swap |
<!-- END GENERATED: fault-codes-avionics -->

### 7.3 Hydraulics Fault Codes

<!-- BEGIN GENERATED: fault-codes-hydraulics -->
| Code | Description | Severity | ATA | Primary Action |
|------|-------------|----------|-----|----------------|
| HYD-LEAK-001 | System Leak | CRIT/MAJ/MIN | 29 | Locate, classify, repair |
| HYD-CNT-002 | Contamination | CRIT/MAJ/MIN | 29 | Sample analysis, filter |
| HYD-PRS-003 | Low Pressure | CRIT/MAJ | 29 | Pump check, leak check |
| HYD-QTY-004 | Low Quantity | MAJ | 29 | Check level, leak inspect |
<!-- END GENERATED: fault-codes-hydraulics -->

### 7.4 Severity Definitions

| Level | Definition | Response Time | Flight Impact |
|-------|------------|---------------|---------------|
| CRITICAL | Safety of flight affected | Immediate | Ground aircraft |
| MAJOR | Significant system degradation | 24-72 hours | May affect dispatch |
| MINOR | Limited impact on operations | Next scheduled maintenance | No dispatch impact |

---

## 8. Troubleshooting Decision Trees

### 8.1 Engine Vibration Diagnostic Flow

<!-- BEGIN GENERATED: vibration-shutdown -->
**Vibration thresholds:** The levels come from the Vibration Limits table in the Vibration Exceedance section. They apply to N1 vibration, the channel the digital twin records. The Warning level starts at 5.0 ips. The Caution level starts at 3.5 ips. The Advisory level starts at 2.0 ips. The tree below names these levels.
<!-- END GENERATED: vibration-shutdown -->

```
START: Vibration Warning Received
│
├─► Is vibration at or above the Warning level?
│   │
│   ├─► YES: Shutdown engine per QRH
│   │        Ground aircraft
│   │        Perform borescope inspection
│   │        └─► END: Major maintenance required
│   │
│   └─► NO: Continue to next step
│
├─► Is vibration at or above the Caution level?
│   │
│   ├─► YES: Plan return to base at earliest opportunity
│   │        Do not cycle thrust unnecessarily
│   │        └─► Proceed to ground troubleshooting
│   │
│   └─► NO: Monitor and continue flight
│            Increase trend monitoring frequency
│
GROUND TROUBLESHOOTING:
│
├─► Perform visual inspection of fan blades
│   │
│   ├─► Damage found: Assess per SRM limits
│   │                 Repair or replace as required
│   │                 └─► END: Fan repair
│   │
│   └─► No damage: Continue
│
├─► Check fan blade balance
│   │
│   ├─► Imbalance detected: Perform fan balance per AMM
│   │                       └─► END: Retest
│   │
│   └─► Balance OK: Continue
│
├─► Review oil debris analysis
│   │
│   ├─► Elevated metals: Bearing wear indicated
│   │                    Schedule engine removal
│   │                    └─► END: Bearing replacement
│   │
│   └─► Normal: Continue
│
└─► Check vibration sensor and wiring
    │
    ├─► Fault found: Repair wiring or replace sensor
    │                └─► END: Sensor repair
    │
    └─► No fault: Document as intermittent
                  Continue monitoring
                  └─► END: Trend analysis
```

### 8.2 Sensor Anomaly Investigation

```
START: Sensor Reading Abnormal
│
├─► Compare with redundant sensor(s)
│   │
│   ├─► Other sensors agree (single sensor fault)
│   │   │
│   │   ├─► Check sensor wiring continuity
│   │   ├─► Verify sensor calibration
│   │   ├─► Inspect connector condition
│   │   └─► Replace sensor if faulty
│   │        └─► END: Single sensor repair
│   │
│   └─► Multiple sensors disagree
│       │
│       └─► Actual system anomaly likely
│           Investigate underlying system
│           └─► See appropriate system troubleshooting
│
└─► Is drift gradual or sudden?
    │
    ├─► Gradual: Calibration drift
    │            Schedule recalibration
    │            Monitor for trend
    │
    └─► Sudden: Likely component failure
               Immediate replacement required
```

### 8.3 Hydraulic Pressure Loss Procedure

```
START: Low Hydraulic Pressure Warning
│
├─► Check reservoir fluid level
│   │
│   ├─► LOW: Leak likely
│   │        Do not operate affected flight controls
│   │        └─► Proceed to leak isolation
│   │
│   └─► NORMAL: Continue
│
├─► Check pump operation
│   │
│   ├─► Pump running, no output: Internal pump failure
│   │                            Replace pump
│   │                            └─► END: Pump replacement
│   │
│   └─► Pump not running: Check drive system
│                         Verify N2 speed adequate
│                         Check pump clutch/coupling
│
├─► LEAK ISOLATION:
│   │
│   ├─► Pressurize system on ground
│   ├─► Systematically isolate sections
│   ├─► Visual inspection of all lines and components
│   │
│   └─► Leak found: Classify severity
│                   Repair per Class A/B/C procedures
│                   └─► END: Leak repair
│
└─► No leak found: Check pressure transducer
                   Verify gauge calibration
                   └─► END: Sensor verification
```

---

## 9. Scheduled Maintenance Tasks

### 9.1 Engine Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fan blade visual inspection | 500 FH | 1.0 hr | 1 mechanic |
| Borescope - HPT | 2,500 FH | 3.0 hr | 1 specialist |
| Borescope - Combustor | 2,500 FH | 2.5 hr | 1 specialist |
| Oil system service | 100 FH | 0.5 hr | 1 mechanic |
| Oil filter change | 600 FH | 1.0 hr | 1 mechanic |
| Fuel filter inspection | 600 FH | 1.0 hr | 1 mechanic |
| Engine mount inspection | A-check | 2.0 hr | 2 mechanics |
| Thrust reverser rigging | C-check | 8.0 hr | 2 mechanics |

### 9.2 Avionics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| FMS database update | 28 days | 0.5 hr | 1 technician |
| ADC leak test | 24 months | 2.0 hr | 1 technician |
| NAV receiver test | 12 months | 1.5 hr | 1 technician |
| Pitot-static system test | 24 months | 4.0 hr | 1 technician |
| BITE self-test review | Weekly | 0.5 hr | 1 technician |

### 9.3 Hydraulics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fluid level check | Daily | 0.25 hr | 1 mechanic |
| Fluid sampling | 600 FH | 0.5 hr | 1 mechanic |
| Filter change | 1,200 FH | 1.5 hr | 1 mechanic |
| Pump inspection | A-check | 2.0 hr | 1 mechanic |
| Actuator rigging check | C-check | 4.0 hr | 2 mechanics |
| System pressure test | 24 months | 3.0 hr | 2 mechanics |

### 9.4 Common Task Cards

#### Task Card: ENG-TC-001 - Engine Oil Sample

**Purpose:** Obtain oil sample for spectrographic analysis

**Tools Required:**
- Sample bottle (clean, dry)
- Drain hose adapter (P/N: V25-TOOL-001)
- Gloves and safety glasses

**Procedure:**
1. Ensure engine has been shut down for minimum 30 minutes
2. Open cowling access panel 54
3. Connect drain hose to sample port
4. Obtain 100ml sample in clean bottle
5. Cap and label sample (aircraft reg, engine position, date, hours)
6. Send to approved laboratory within 24 hours

**Completion:** Sign off in aircraft technical log

#### Task Card: HYD-TC-001 - Hydraulic Fluid Level Check

**Purpose:** Verify adequate fluid level for dispatch

**Reference:** AMM 29-11-00

**Procedure:**
1. Ensure all hydraulic systems depressurized
2. Check sight glass on each reservoir
3. Level should be between MIN and MAX marks
4. If low, replenish with approved fluid only
5. Document quantity added in tech log

---

## 10. Appendices

### 10.1 Quick Reference - Normal Operating Limits

#### Engine Parameters (V2500-A1)

<!-- BEGIN GENERATED: quick-ref-engine -->
| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) | Max Continuous | Takeoff (5 min) |
|-----------|-------------|-------------|-----------------------|----------------|-----------------|
| N1Speed (%) | 22 | 28 | 87 (85-89) | 97 | 104 |
| N2 (%) | 58 | 65 | — | 97 | 102 |
| EGT (°C) | 380 | 450 | 560 (< 580) | < 620 | < 650 |
| FuelFlow (kg/s) | 0.15-0.25 | 0.15-0.25 | 0.34 (0.31-0.37) | 0.85-1.20 | 1.20-1.95 |
| Oil Pressure (psi) | 25-55 | 40-65 | — | 40-65 | 40-65 |
| Oil Temperature (°C) | 40-90 | 60-120 | — | 60-150 | 60-155 |
| Vibration N1 (ips) | < 2.0 | < 2.0 | 0.8 (< 2.0) | < 2.0 | < 2.0 |
<!-- END GENERATED: quick-ref-engine -->

#### Hydraulic System

<!-- BEGIN GENERATED: quick-ref-hydraulics -->
| Parameter | Nominal | Normal | Advisory | Caution | Warning |
|-----------|---------|--------|----------|---------|---------|
| Hydraulic Pressure (psi) | 3,000 | > 2,800 | 2,600-2,800 | 2,400-2,600 | ≤ 2,400 |
| Hydraulic Fluid Quantity (%) | 90 | > 70 | 60-70 | 50-60 | ≤ 50 |
<!-- END GENERATED: quick-ref-hydraulics -->

The bands apply to every hydraulic system.

**Fluid temperature:** The Green, Blue, and Yellow systems each operate from -40 to +100°C. Above 110°C is a warning.

### 10.2 Abbreviations and Acronyms

| Abbreviation | Definition |
|--------------|------------|
| ADC | Air Data Computer |
| AMM | Aircraft Maintenance Manual |
| ATA | Air Transport Association |
| BITE | Built-In Test Equipment |
| DFDR | Digital Flight Data Recorder |
| ECAM | Electronic Centralized Aircraft Monitor |
| EGT | Exhaust Gas Temperature |
| FH | Flight Hours |
| FMS | Flight Management System |
| FOD | Foreign Object Damage |
| HPC | High Pressure Compressor |
| HPT | High Pressure Turbine |
| IAE | International Aero Engines |
| LRU | Line Replaceable Unit |
| NAV | Navigation |
| QAR | Quick Access Recorder |
| QRH | Quick Reference Handbook |
| SFCC | Slat/Flap Control Computer |
| SRM | Structural Repair Manual |
| TAN | Total Acid Number |

### 10.3 Reference Documents

| Document | Number | Description |
|----------|--------|-------------|
| Aircraft Maintenance Manual | AMM A320 | Primary maintenance reference |
| Fault Isolation Manual | FIM A320 | Troubleshooting procedures |
| Illustrated Parts Catalog | IPC A320 | Parts identification |
| Component Maintenance Manual | CMM V2500 | Engine overhaul procedures |
| Service Bulletin Index | SB A320 | Modification status |
| Airworthiness Directives | AD List | Mandatory compliance items |

### 10.4 Emergency Contacts

| Function | Contact | Availability |
|----------|---------|--------------|
| AOG Desk | +1-800-555-0199 | 24/7 |
| Engine Manufacturer (IAE) | +1-860-555-0123 | Business hours |
| Technical Records | tech.records@skyways.aero | 24/7 |
| Engineering Support | engineering@skyways.aero | 24/7 |
| Parts Supply | parts@skyways.aero | 24/7 |

### 10.5 Fleet Maintenance Statistics

<!-- BEGIN GENERATED: fleet-statistics -->
These figures are counts from this demo's generated fleet data: 30 aircraft over 90 days, seed 42. The A320-200 has 5 of the aircraft and 36 of the maintenance events.

**Events by Severity:**

| Severity | Events | Share |
|----------|--------|-------|
| Critical | 7 | 19% |
| Major | 7 | 19% |
| Minor | 22 | 61% |

**Events by System:**

| System | Events | Share |
|--------|--------|-------|
| Engine | 21 | 58% |
| Avionics | 6 | 17% |
| Hydraulics | 9 | 25% |

**Events by Fault:**

| Fault | System | Events | Share |
|-------|--------|--------|-------|
| Overheat | Engine | 7 | 19% |
| Vibration exceedance | Engine | 7 | 19% |
| Leak | Hydraulics | 7 | 19% |
| Sensor drift | Engine | 4 | 11% |
| Sensor drift | Avionics | 4 | 11% |
| Bearing wear | Engine | 3 | 8% |
| Electrical fault | Avionics | 2 | 6% |
| Contamination | Hydraulics | 2 | 6% |
<!-- END GENERATED: fleet-statistics -->

### 10.6 Revision History Log

| Page | Rev | Date | Change Description |
|------|-----|------|--------------------|
| All | 1.0 | 2024-10-01 | Initial release |

---

**END OF DOCUMENT**

*This manual is for demonstration purposes. Always refer to official Airbus documentation for actual maintenance procedures.*
