# E190 Maintenance and Troubleshooting Manual

**Document Number:** AMM-E190-2024-001
**Revision:** 1.0
**Effective Date:** October 1, 2024
**Applicability:** E190 series aircraft equipped with CF34-10E engines
**Operator:** ExampleAir, SkyWays, RegionalCo, NorthernJet
**Fleet:** N10002, N10017, N10023, N10036, N10050, N10068, N10071, N10073, N10084, N10096

---

## Document Control

| Rev | Date | Description | Author |
|-----|------|-------------|--------|
| 1.0 | 2024-10-01 | Initial Release | Engineering Division |
| 0.9 | 2024-09-15 | Draft for review | Maintenance Planning |

**NOTICE:** This manual contains proprietary information. Maintenance procedures must be performed by certified personnel only. Always refer to the latest revision of Embraer AMM documentation for authoritative guidance.

---

## Table of Contents

1. [Aircraft Overview](#1-aircraft-overview)
2. [System Architecture](#2-system-architecture)
3. [Engine System - CF34-10E](#3-engine-system---cf34-10e)
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
| Aircraft Type | Embraer E190 (E-Jet series) |
| Powerplant | 2x GE Aviation CF34-10E Turbofan |
| Maximum Takeoff Weight (MTOW) | 51,800 kg (114,200 lb) |
| Maximum Landing Weight (MLW) | 44,000 kg (97,003 lb) |
| Maximum Zero Fuel Weight (MZFW) | 41,000 kg (90,390 lb) |
| Fuel Capacity | 13,986 liters (3,694 US gal) |
| Range | 4,537 km (2,450 nm) |
| Service Ceiling | 41,000 ft |
| Cruise Speed | Mach 0.82 |

### 1.2 Fleet Configuration

The E190 fleet operates across four partner carriers in regional jet service.

| Operator | Registrations | Primary Routes |
|----------|---------------|----------------|
| ExampleAir | N10002, N10017, N10023 | Domestic regional feeders |
| SkyWays | N10036, N10050, N10068 | Domestic regional feeders |
| RegionalCo | N10071, N10073 | Regional and short-haul |
| NorthernJet | N10084, N10096 | Northern domestic regional |

Aircraft entered service between 2018 and 2022, configured in a two-class layout for 94–100 passengers. Regional operations result in higher cycle-to-flight-hour ratios compared to wide-body or long-haul fleets, making cycle-based inspection compliance particularly important.

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
| ATA 79 | Oil | Section 3 |

---

## 2. System Architecture

### 2.1 Major System Groups

Each E190 aircraft comprises four primary monitored system groups:

<!-- BEGIN GENERATED: component-tree -->
```
AIRCRAFT (E190)
│
├── ENGINE SYSTEM #1 (CF34-10E Left)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── ENGINE SYSTEM #2 (CF34-10E Right)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── AVIONICS SYSTEM
│   ├── Flight Management System (FMS)
│   ├── Air Data and Inertial Reference Unit (ADIRU)
│   └── Multi-Mode Receiver (MMR)
│
└── HYDRAULICS SYSTEM
    ├── Engine-Driven Pump
    ├── Hydraulic Reservoir
    └── Flap Actuator Assembly
```
<!-- END GENERATED: component-tree -->

#### 2.1.1 Engine Systems (CF34-10E)

The E190 is powered by two GE Aviation CF34-10E high-bypass turbofan engines, mounted on aft-fuselage pylons in the characteristic E-Jet configuration that provides unobstructed underwing space and a low-slung cabin floor. Each engine produces 18,500 lbf of thrust at takeoff and operates independently with full redundancy. The CF34-10E features a two-spool architecture with a single-stage fan driven by a multi-stage low-pressure turbine and a 9-stage high-pressure compressor driven by a single-stage high-pressure turbine, achieving an overall pressure ratio of 27.0:1. The engine incorporates an annular combustor with low-emissions fuel nozzle design. Engine health is continuously monitored via four dedicated sensors per engine measuring exhaust gas temperature (EGT), vibration levels, fan speed (N1), and fuel flow rate.

<!-- BEGIN GENERATED: system-shares-engine -->
In the generated fleet data, engine systems account for 48 of the E190's 74 maintenance events, or 65%. The most common engine faults are overheat with 15 events, bearing wear with 12, and sensor drift with 10.
<!-- END GENERATED: system-shares-engine -->

**ATA Reference:** Chapters 71 (Powerplant), 72 (Engine), 73 (Engine Fuel and Control), 77 (Engine Indicating), 79 (Oil)

#### 2.1.2 Avionics System

The avionics system provides flight management, navigation, and air data computation functions essential for safe aircraft operation. The E190 features the Honeywell Primus Epic EFIS with dual Flight Management Systems providing 4D flight planning, performance calculations, and VNAV/LNAV guidance. Three Air Data / Inertial Reference Units (ADIRU) supply redundant altitude, airspeed, Mach, and inertial reference data integrated with the digital fly-by-wire flight control system. Multi-Mode Receivers (MMR) provide VOR/DME, ILS (localizer, glideslope, marker beacon), and GPS position data. All avionics communicate via ARINC 429 digital data buses with comprehensive Built-In Test Equipment (BITE).

<!-- BEGIN GENERATED: system-shares-avionics -->
In the generated fleet data, avionics accounts for 15 of the E190's 74 maintenance events, or 20%. The avionics faults are electrical fault with 10 events and sensor drift with 5.
<!-- END GENERATED: system-shares-avionics -->

Avionics faults are typically resolved through calibration or software updates.

**ATA Reference:** Chapter 34 (Navigation)

#### 2.1.3 Hydraulics System

The E190 hydraulic system provides power for flight control surfaces, spoilers, leading edge slats, trailing edge flaps, landing gear, wheel brakes, thrust reversers, and nose wheel steering. The aircraft employs two primary hydraulic systems designated Left and Right, each operating at 3,000 psi, plus a standby system for emergency backup. The Left system is powered by two engine-driven pumps (one per engine) and one AC motor pump. Each system reservoir holds 4.0 gallons usable capacity. Hydraulic fluid (MIL-PRF-83282 or Skydrol 5) requires regular monitoring for contamination and proper fluid levels.

<!-- BEGIN GENERATED: system-shares-hydraulics -->
In the generated fleet data, the hydraulics system accounts for 11 of the E190's 74 maintenance events, or 15%. The hydraulics faults are leak with 9 events and contamination with 2.
<!-- END GENERATED: system-shares-hydraulics -->

**ATA Reference:** Chapter 29 (Hydraulic Power)

### 2.2 Engine Health Monitoring

<!-- BEGIN GENERATED: sensor-table -->
Each CF34-10E engine carries four monitoring sensors. The Avionics and Hydraulics systems carry two sensors each. The digital twin records every sensor hourly.

| System | Sensor Type | Parameter | Unit | Location |
|--------|-------------|-----------|------|----------|
| Engine | EGT | Exhaust Gas Temperature | °C | Turbine exhaust section |
| Engine | Vibration | Engine Vibration | ips | Fan frame, turbine frame |
| Engine | N1Speed | Fan Speed N1 | % | Fan shaft |
| Engine | FuelFlow | Fuel Flow | kg/s | Fuel metering valve |
| Avionics | BusVoltage | DC Bus Voltage | V DC | DC essential bus |
| Avionics | AirDataDisagree | Air Data Airspeed Disagreement | kt | Captain and first officer air data sources |
| Hydraulics | HydPressure | Hydraulic Pressure | psi | System pressure manifold |
| Hydraulics | HydQuantity | Hydraulic Fluid Quantity | % | Hydraulic reservoir |
<!-- END GENERATED: sensor-table -->

**Sensor Sampling Rate:** Continuous (1 Hz during flight, recorded hourly for trend analysis)

<!-- BEGIN GENERATED: egt-trend-note -->
**Digital Twin Monitoring Note:** The Digital Twin Monitoring System records hourly trend-averaged EGT values on a normalized scale calibrated for long-term degradation detection. For the CF34-10E, the trend baseline is 641°C, with Advisory at 661°C, Caution at 671°C, and Warning at 681°C. These trend values differ from the instantaneous EGT limits in the Normal Operating Parameters table and Appendix 10.1, which reflect peak values during takeoff and high-power operations. The trend scale detects gradual EGT margin deterioration over weeks and months, not acute exceedances. The absolute limits in this manual refer to instantaneous FADEC-monitored readings.
<!-- END GENERATED: egt-trend-note -->

Instantaneous takeoff EGT for the CF34-10E7 must stay within the Operating Limits table in section 3.2.3, High-Pressure Turbine.

**FADEC Integration:** The CF34-10E features Full Authority Digital Engine Control (FADEC) which provides automatic engine parameter management, thrust setting, and fault detection/isolation.

### 2.3 Component Identification Schema

Components are identified using the following nomenclature:

<!-- BEGIN GENERATED: component-ids -->
```
[Aircraft ID]-[System]-[Component]

Example: AC1004-S01-C03
         │       │    └── Component: High-Pressure Turbine
         │       └─────── System: Engine #1
         └─────────────── Aircraft: AC1004 (N10002)
```

**System Codes:**
- S01: Engine #1 (Left)
- S02: Engine #2 (Right)
- S03: Avionics
- S04: Hydraulics
<!-- END GENERATED: component-ids -->

---

## 3. Engine System - CF34-10E

### 3.1 Engine Specifications

| Parameter | Value |
|-----------|-------|
| Manufacturer | GE Aviation |
| Model | CF34-10E |
| Type | Two-spool, high-bypass turbofan |
| Thrust Rating | 18,500 lbf (82.3 kN) |
| Bypass Ratio | 5.0:1 |
| Overall Pressure Ratio | 27.0:1 |
| Dry Weight | 1,620 kg (3,571 lb) |
| Fan Diameter | 1.23 m (48.4 in) |
| Length | 2.44 m (96 in) |

### 3.2 Component Descriptions

#### 3.2.1 Fan Module
**Part Number:** CFM-FM-CF34-100
**ATA Reference:** 72-21

The fan module consists of a single-stage fan with 22 wide-chord titanium blades without mid-span shrouds, providing improved aerodynamic efficiency and reduced weight compared to earlier CF34 variants. The fan provides approximately 75% of total engine thrust through the bypass duct. Fan blades feature 3D aerodynamic design with swept leading edges optimized for the CF34-10E's bypass ratio and pressure recovery.

**Inspection Intervals:**
- Visual inspection: Every 500 flight hours
- Borescope inspection: Every 3,000 flight hours
- Fan blade replacement: On-condition (typically 18,000-22,000 cycles)

**Critical Limits:**
- Fan blade tip clearance: 0.055-0.085 inches cold
- Fan track liner wear limit: 0.110 inches

#### 3.2.2 Compressor Stage (High-Pressure)
**Part Number:** GE-HPC-CF34-200
**ATA Reference:** 72-32

The 9-stage high-pressure compressor (HPC) achieves a pressure ratio of approximately 12.5:1. The first three stages feature variable stator vanes (VSV) controlled by the FADEC for optimum performance and stall margin across the operating envelope.

**Common Fault Modes:**
- Compressor stall (vibration exceedance)
- Blade tip erosion (performance degradation)
- Variable stator vane actuator malfunction (sensor drift)
- FOD damage (leading edge nicks and tears)

**Borescope Inspection Points:**
- Stage 1 blades: Leading edge erosion
- Stage 5 blades: Mid-chord cracking
- Stage 9 blades: Tip rub damage

#### 3.2.3 High-Pressure Turbine
**Part Number:** GE-HPT-CF34-300
**ATA Reference:** 72-51

The single-stage HPT drives the high-pressure compressor through a concentric shaft. Turbine blades feature advanced single-crystal alloy construction with thermal barrier coating and film cooling. The nozzle guide vanes are air-cooled with impingement and film cooling optimized for the CF34-10E's turbine inlet temperature.

**Operating Limits:**
<!-- BEGIN GENERATED: egt-limits -->
| Parameter | Normal | Caution | Maximum |
|-----------|--------|---------|---------|
| EGT (Takeoff, 5 min) | < 870°C | 870-895°C | 900°C |
| EGT (Max Continuous) | < 840°C | 840-870°C | 870°C |
| EGT (Start) | — | — | 730°C |
<!-- END GENERATED: egt-limits -->

**Life-Limited Parts:**
- HPT disk: 18,000 cycles
- HPT blades: On-condition (borescope monitoring)

#### 3.2.4 Main Fuel Pump
**Part Number:** GE-FP-CF34-400
**ATA Reference:** 73-21

The engine-driven fuel pump is a positive displacement gear pump providing metered fuel flow to the combustion chamber through the fuel metering valve (FMV). The hydromechanical unit (HMU) integrates the fuel pump with the fuel metering valve under FADEC control.

**Flow Rate:** 0.20 - 1.20 kg/s (normal operating range)

**Warning Signs of Degradation:**
- Fluctuating fuel flow readings
- High fuel filter delta-P indication (EICAS message)
- Fuel pump inlet pressure low
- Uncommanded thrust changes

#### 3.2.5 Thrust Bearing Assembly
**Part Number:** GE-TB-CF34-500
**ATA Reference:** 72-50

The thrust bearing absorbs axial loads from the high-pressure rotor system. The bearing is a ball-type design with squeeze film damper and oil jet lubrication from the engine oil system.

**Replacement Criteria:**
- Oil debris analysis: Magnetic chip detector warnings
- Bearing temperature rise > 20°C above baseline
- Vibration increase traceable to bearing frequency
- Oil consumption exceeding 0.4 qt/hr

### 3.3 Normal Operating Parameters

<!-- BEGIN GENERATED: normal-parameters -->
| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) | Max Continuous | Takeoff (5 min) |
|-----------|-------------|-------------|-----------------------|----------------|-----------------|
| N1Speed (%) | 22-28 | 28-35 | 87 (85-89) | 96 | 100 |
| EGT (°C) | 330-400 | 400-460 | 641 (< 661) | < 840 | < 870 |
| FuelFlow (kg/s) | 0.08-0.15 | 0.15-0.22 | 0.27 (0.25-0.29) | 0.75-0.95 | 1.00-1.20 |
| Oil Pressure (psi) | 35-60 | 40-70 | — | 45-75 | 45-75 |
| Oil Temperature (°C) | 50-90 | 60-120 | — | 80-140 | 80-155 |
| Vibration N1 (ips) | < 2.0 | < 2.0 | 0.8 (< 2.0) | < 2.0 | < 2.0 |
<!-- END GENERATED: normal-parameters -->

### 3.4 FADEC System

The Full Authority Digital Engine Control (FADEC) provides:

- Automatic engine start sequencing
- Thrust management (N1 limit computation)
- Fuel metering control
- Variable stator vane scheduling
- Transient bleed valve control
- Active clearance control
- Engine limit protection
- Fault detection and isolation

**FADEC Redundancy:** Dual-channel with automatic switchover

**Manual Reversion:** Not available - FADEC failure requires engine shutdown

---

## 4. Engine Troubleshooting Procedures

### 4.1 Sensor Drift

**Fault Code:** ENG-SDR-001
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-sensor-drift -->
**Fleet Statistics:** In the generated fleet data, sensor drift accounts for 10 of the E190's 48 engine maintenance events, or 21%.
<!-- END GENERATED: fault-stats-engine-sensor-drift -->

#### Symptoms
- Parameter disagree messages on EICAS
- Gradual deviation between redundant sensor readings
- Thrust asymmetry indications
- FADEC fault messages

#### Diagnostic Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Review FADEC fault log via CMC | Identify affected channel and parameter |
| 2 | Compare sensor values (Channel A vs B) | Determine which channel has drifted |
| 3 | Cross-check with independent references | Validate actual engine condition |
| 4 | Perform sensor Built-In Test (BIT) | Confirm sensor hardware status |
| 5 | Check wiring continuity and connections | Rule out intermittent connections |

#### Corrective Actions by Severity

**CRITICAL (Drift > 10% affecting thrust control):**
- Ground aircraft pending sensor replacement
- Replace affected sensor or EEC channel
- Perform engine ground run verification
- Estimated downtime: 8-12 hours

**MAJOR (Drift 5-10%, redundancy compromised):**
- Dispatch with MEL if applicable
- Schedule sensor replacement within 10 days
- Increase monitoring frequency

**MINOR (Drift < 5%, trending):**
- Document in aircraft log
- Schedule calibration check at next maintenance visit
- Continue trend monitoring

### 4.2 Contamination

**Fault Code:** ENG-CNT-002
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-contamination -->
**Fleet Statistics:** In the generated fleet data, contamination accounts for 3 of the E190's 48 engine maintenance events, or 6%.
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
| 1 | Review trend data for EGT margin degradation | > 5°C shift indicates fouling |
| 2 | Perform oil spectrographic analysis | Check for wear metals, contamination |
| 3 | Check fuel filter differential pressure | High DP indicates fuel contamination |
| 4 | Borescope HPT nozzle and blades | Visual deposits, coating loss |
| 5 | Perform compressor wash if applicable | Evaluate EGT margin recovery |

#### Corrective Actions

**CRITICAL (Severe contamination affecting operation):**
- Engine removal for shop cleaning
- HPT blade replacement if sulfidation present
- Oil system flush and filter replacement
- Estimated downtime: 3-5 days

**MAJOR (Moderate contamination):**
- Perform on-wing compressor wash (motoring wash)
- Replace fuel filter element
- Enhanced oil sampling (every 25 FH)
- Monitor EGT margin recovery

**MINOR (Early detection):**
- Schedule compressor wash at next opportunity
- Increase fuel sampling frequency
- Document trend for fleet analysis

### 4.3 Bearing Wear

**Fault Code:** ENG-BRG-003
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-bearing-wear -->
**Fleet Statistics:** In the generated fleet data, bearing wear accounts for 12 of the E190's 48 engine maintenance events, or 25%.
<!-- END GENERATED: fault-stats-engine-bearing-wear -->

#### Detection Methods
- Magnetic chip detector (MCD) warnings
- Oil spectrographic analysis (SOAP)
- Vibration trend monitoring
- Oil consumption increase
- Oil temperature rise

#### Oil Analysis Limits (CF34-10E Specific)

| Metal | Normal (ppm) | Watch (ppm) | Action (ppm) |
|-------|--------------|-------------|--------------|
| Iron (Fe) | < 4 | 4-10 | > 10 |
| Chromium (Cr) | < 1 | 1-3 | > 3 |
| Nickel (Ni) | < 2 | 2-5 | > 5 |
| Silver (Ag) | < 0.5 | 0.5-2 | > 2 |
| Copper (Cu) | < 5 | 5-15 | > 15 |

#### Bearing Identification by Vibration Frequency

| Bearing | Location | N1 Frequency | N2 Frequency |
|---------|----------|--------------|--------------|
| #1 | Fan forward | 1.0 × N1 | — |
| #2 | Fan aft | 1.0 × N1 | — |
| #3 | HPC forward | — | 1.0 × N2 |
| #4 (Thrust) | HPC aft | — | 1.0 × N2 |
| #5 | HPT/LPT | — | 1.0 × N2 |

#### Corrective Actions

**CRITICAL (MCD activation or rapid debris increase):**
- Immediate engine shutdown
- Do not motor engine
- Remove engine for teardown inspection
- Estimated downtime: Engine replacement required

**MAJOR (Elevated wear metals, trending):**
- Increase oil sampling to every 25 FH
- Plan engine removal within 200 FH
- Monitor vibration closely
- No power above MCT

**MINOR (Slight increase, stable):**
- Increase sampling frequency to every 50 FH
- Continue normal operations
- Trend monitoring with fleet comparison

### 4.4 Leak Detection

**Fault Code:** ENG-LEAK-004
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-leak -->
**Fleet Statistics:** In the generated fleet data, leak accounts for 4 of the E190's 48 engine maintenance events, or 8%.
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
| Fuel | HMU connections | Wet fittings |
| Bleed | Duct connections | Sooting, heat damage |

#### Troubleshooting Procedure

| Step | Action | Inspection Point |
|------|--------|------------------|
| 1 | Perform visual inspection of engine nacelle and pylon | Note all fluid trails |
| 2 | Clean suspected areas thoroughly | Prepare for leak check |
| 3 | Operate engine at ground idle | Observe for fresh leaks |
| 4 | Apply leak detection solution | Bubble test for pneumatic |
| 5 | UV dye inspection (if oil dye installed) | Pinpoint oil leak source |

### 4.5 Vibration Exceedance

**Fault Code:** ENG-VIB-005
**Severity Classification:** CRITICAL / MAJOR / MINOR
<!-- BEGIN GENERATED: fault-stats-engine-vibration-exceedance -->
**Fleet Statistics:** In the generated fleet data, vibration exceedance accounts for 4 of the E190's 48 engine maintenance events, or 8%.
<!-- END GENERATED: fault-stats-engine-vibration-exceedance -->

#### Vibration Limits (CF34-10E)

<!-- BEGIN GENERATED: vibration-bands -->
| Level | N1 Vibration | Event Severity | Flight Deck Alert |
|-------|--------------|----------------|-------------------|
| Normal | < 2.0 ips | None | None |
| Advisory | 2.0-3.0 ips | MINOR | ENG VIB (amber) |
| Caution | 3.0-4.0 ips | MAJOR | ENG VIB (amber) |
| Warning | ≥ 4.0 ips | CRITICAL | ENG VIB (red) |
<!-- END GENERATED: vibration-bands -->

#### Common Root Causes

| Cause | Frequency Signature | Typical Origin |
|-------|--------------------| ---------------|
| Fan imbalance | 1 × N1 | Blade damage, ice |
| Core imbalance | 1 × N2 | HPC blade loss |
| Bearing | 1 × N1 or N2 | Bearing degradation |
| Gear mesh | Multiple of N2 | AGB wear |

---

## 5. Avionics System

### 5.1 System Overview

The E190 avionics suite is built around the Honeywell Primus Epic EFIS with fully integrated digital avionics architecture. The system provides glass-cockpit displays, integrated flight management, fly-by-wire flight control interface, and comprehensive BITE diagnostics.

### 5.2 Component Descriptions

#### 5.2.1 Flight Management System (FMS)
**Part Number:** AVN-FMS-E190-100
**ATA Reference:** 34-61

The Honeywell Primus Epic dual FMS provides:
- 4D flight planning and navigation
- VNAV and LNAV guidance
- Performance calculations (V-speeds, fuel predictions)
- Required Navigation Performance (RNP) capability
- FANS datalink integration

**Common Faults:**
- Navigation database update errors
- CDU display anomalies
- Position initialization failures

#### 5.2.2 Air Data / Inertial Reference Unit (ADIRU)
**Part Number:** AVN-ADIRU-E190-200
**ATA Reference:** 34-11

Three independent ADIRUs provide:
- Barometric altitude computation
- Indicated/calibrated airspeed
- Mach number calculation
- Static air temperature
- Inertial reference (attitude, heading, acceleration)

**Calibration Requirements:**
- Pitot-static leak test: Every 24 months
- ADIRU accuracy verification: Every 12 months

#### 5.2.3 Multi-Mode Receiver (MMR)
**Part Number:** AVN-MMR-E190-300
**ATA Reference:** 34-51

Integrated Multi-Mode Receiver providing:
- VOR bearing and distance (VOR/DME)
- ILS localizer and glideslope
- Marker beacon reception
- GPS position (L1 frequency)

### 5.3 Avionics Troubleshooting

#### 5.3.1 Sensor Drift (Avionics)

**Fault Code:** AVN-SDR-001
<!-- BEGIN GENERATED: fault-stats-avionics-sensor-drift -->
**Fleet Statistics:** In the generated fleet data, sensor drift accounts for 5 of the E190's 15 avionics maintenance events, or 33%.
<!-- END GENERATED: fault-stats-avionics-sensor-drift -->

**Diagnostic Steps:**
1. Compare ADIRU outputs (ADIRU 1/2/3) via maintenance page
2. Cross-check with GPS-derived altitude and airspeed
3. Review BITE fault history for intermittent faults
4. Check pitot-static system for leaks or blockage

**Resolution:**
- Pitot-static leak check and correction
- ADIRU software reload
- ADIRU replacement if hardware fault confirmed

---

## 6. Hydraulics System

### 6.1 System Overview

The E190 employs a dual hydraulic system (Left and Right) plus standby, operating at 3,000 psi. Left and Right systems each power separate portions of the primary flight controls, with crossover capability for redundancy.

### 6.2 System Architecture

| System | Power Source | Primary Functions |
|--------|--------------|-------------------|
| Left | EDP (Eng 1), EDP (Eng 2), ACMP | Flight controls (50%), LE slats, flaps, gear |
| Right | EDP (Eng 1), EDP (Eng 2), ACMP | Flight controls (50%), TE flaps, thrust reversers |
| Standby | ACMP | Standby rudder, LE slats, thrust reversers |

### 6.3 Component Descriptions

#### 6.3.1 Engine-Driven Pump
**Part Number:** HYD-EDP-E190-100
**ATA Reference:** 29-11

Each engine drives one pump for the Left system and one for the Right system:
- Operating pressure: 3,000 psi nominal
- Flow rate: 20 gpm at 3,000 psi
- Case drain limit: 4 gpm

#### 6.3.2 Hydraulic Reservoir
**Part Number:** HYD-RES-E190-200
**ATA Reference:** 29-21

- Left system reservoir: 4.0 gallons usable
- Right system reservoir: 4.0 gallons usable
- Standby reservoir: 0.6 gallons usable
- Operating temperature: -54°C to +107°C
- Fluid type: MIL-PRF-83282 or Skydrol 5

#### 6.3.3 Flap Actuator Assembly
**Part Number:** HYD-FLAP-E190-300
**ATA Reference:** 29-31

The trailing edge flap system uses:
- Power Drive Unit (PDU) with dual hydraulic motors
- Rotary actuators at each flap panel
- Position feedback via flap position transmitters

### 6.4 Hydraulics Troubleshooting

#### 6.4.1 Leak Detection

**Fault Code:** HYD-LEAK-001
<!-- BEGIN GENERATED: fault-stats-hydraulics-leak -->
**Fleet Statistics:** In the generated fleet data, leak accounts for 9 of the E190's 11 hydraulics maintenance events, or 82%.
<!-- END GENERATED: fault-stats-hydraulics-leak -->

**Common Leak Locations:**

| Component | Access | Typical Cause |
|-----------|--------|---------------|
| EDP | Engine nacelle | Shaft seal wear |
| ACMP | Avionics bay | Pump seal, fittings |
| Reservoir | Avionics bay | Sight glass gasket |
| Actuators | Wing panels | Rod seal wear |
| Lines | Various | B-nut loosening |

**Leak Check Procedure:**
1. Depressurize hydraulic systems
2. Clean and dry suspected areas
3. Pressurize system using ground cart
4. Inspect for fresh fluid at suspected locations
5. Classify leak severity and document

#### 6.4.2 Contamination

**Fault Code:** HYD-CNT-002
<!-- BEGIN GENERATED: fault-stats-hydraulics-contamination -->
**Fleet Statistics:** In the generated fleet data, contamination accounts for 2 of the E190's 11 hydraulics maintenance events, or 18%.
<!-- END GENERATED: fault-stats-hydraulics-contamination -->

**Contamination Limits (NAS 1638):**

| Level | Class | Action |
|-------|-------|--------|
| Acceptable | 6 or better | Continue operations |
| Marginal | 7-8 | Filter and resample in 100 FH |
| Unacceptable | 9 or worse | Flush system, replace filters |

**Water Content:** Maximum 0.1% by volume

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
| AVN-SDR-001 | Sensor Drift | CRIT/MAJ/MIN | 34 | ADIRU comparison, calibration |
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

| Level | Definition | Response Time | MEL Impact |
|-------|------------|---------------|------------|
| CRITICAL | Flight safety affected | Before next flight | No-go item |
| MAJOR | System capability reduced | 1-10 days | Dispatch deviation |
| MINOR | Limited operational impact | Next scheduled mx | Normal dispatch |

---

## 8. Troubleshooting Decision Trees

### 8.1 Engine Vibration Diagnostic Flow

<!-- BEGIN GENERATED: vibration-shutdown -->
**Vibration thresholds:** The levels come from the Vibration Limits table in the Vibration Exceedance section. They apply to N1 vibration, the channel the digital twin records. The Warning level starts at 4.0 ips. The Caution level starts at 3.0 ips. The Advisory level starts at 2.0 ips. The tree below names these levels.
<!-- END GENERATED: vibration-shutdown -->

```
START: Engine Vibration Warning/Advisory
│
├─► Is vibration at or above the Warning level?
│   │
│   ├─► YES ─► Reduce thrust immediately
│   │          If vibration stays at the Warning level, shutdown engine
│   │          └─► END: Engine shutdown, ground inspection required
│   │
│   └─► NO ─► Continue to next step
│
├─► Analyze vibration frequency spectrum (DFDR/QAR)
│   │
│   ├─► 1×N1 dominant ─► Fan rotor issue
│   │   ├─► Check fan blades for damage, ice, deposits
│   │   ├─► Perform fan trim balance if imbalance confirmed
│   │   └─► END: Fan service
│   │
│   ├─► 1×N2 dominant ─► Core rotor issue
│   │   ├─► Borescope HPC and HPT
│   │   ├─► Check oil analysis for bearing wear
│   │   └─► END: Core inspection/repair
│   │
│   └─► Bearing frequency ─► Bearing degradation
│       ├─► Immediate oil sample for SOAP
│       ├─► If metals elevated, plan engine removal
│       └─► END: Bearing replacement (shop)
│
└─► Vibration transient only?
    │
    ├─► YES ─► Document, monitor for recurrence
    │          Check for icing conditions at time of event
    │          └─► END: Monitoring
    │
    └─► NO ─► Systematic component inspection required
              └─► END: Detailed troubleshooting
```

### 8.2 Sensor Drift Investigation

```
START: Sensor Parameter Disagree / Drift Indication
│
├─► Which parameter is affected?
│   │
│   ├─► EGT ─► Compare EGT probes (8 total per engine)
│   │          Check for probe damage, contamination
│   │          Verify harness connections
│   │          └─► Replace probe if > 15°C variance
│   │
│   ├─► N1Speed ─► Compare FADEC channels A and B
│   │              Check speed sensor tone wheel
│   │              Verify wiring to EEC
│   │              └─► Replace sensor or EEC channel
│   │
│   ├─► FuelFlow ─► Compare commanded vs actual
│   │               Check fuel flow transmitter
│   │               Verify FMV operation
│   │               └─► Replace transmitter or HMU
│   │
│   └─► Vibration ─► Compare accelerometer outputs
│                   Check mounting and wiring
│                   └─► Replace accelerometer
│
└─► Is drift progressive or sudden?
    │
    ├─► Progressive ─► Calibration drift likely
    │                  Schedule replacement at next mx
    │                  └─► END: Scheduled repair
    │
    └─► Sudden ─► Component failure likely
                 Replace before next flight
                 └─► END: Immediate repair
```

### 8.3 Hydraulic Low Pressure Procedure

```
START: HYD SYS PRESS (Left or Right) Warning
│
├─► Check hydraulic quantity
│   │
│   ├─► QUANTITY LOW ─► Leak present
│   │   ├─► Land at nearest suitable airport
│   │   ├─► Do not cycle gear unnecessarily
│   │   ├─► After landing, inspect for leak source
│   │   └─► END: Leak repair required
│   │
│   └─► QUANTITY NORMAL ─► Pump issue likely
│
├─► Check pump status (EDP or ACMP)
│   │
│   ├─► EDP ─► Is engine running normally?
│   │   ├─► YES ─► EDP internal failure
│   │   │          Use alternate pump
│   │   │          └─► END: Replace EDP
│   │   │
│   │   └─► NO ─► Engine problem affecting pump drive
│   │            └─► See engine troubleshooting
│   │
│   └─► ACMP ─► Check circuit breaker and power
│               Check motor operation
│               └─► END: Replace ACMP if faulty
│
└─► Pressure restored with alternate pump?
    │
    ├─► YES ─► Primary pump failed
    │          Can dispatch per MEL with restrictions
    │          └─► END: Schedule pump replacement
    │
    └─► NO ─► System blockage or multiple failures
              Do not dispatch
              └─► END: Extensive troubleshooting required
```

---

## 9. Scheduled Maintenance Tasks

### 9.1 Engine Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fan blade visual inspection | 500 FH | 0.75 hr | 1 mechanic |
| Engine oil service | 50 FH or 7 days | 0.5 hr | 1 mechanic |
| Oil filter inspection | 500 FH | 1.0 hr | 1 mechanic |
| Magnetic chip detector check | 500 FH | 0.5 hr | 1 mechanic |
| Borescope - HPC | 3,000 FH | 3.0 hr | 1 specialist |
| Borescope - Combustor | 3,000 FH | 2.0 hr | 1 specialist |
| Borescope - HPT | 3,000 FH | 2.5 hr | 1 specialist |
| Fuel filter replacement | 1,200 FH | 1.5 hr | 1 mechanic |
| Engine mount inspection | A-check | 2.5 hr | 2 mechanics |
| Thrust reverser inspection | C-check | 12.0 hr | 2 mechanics |

### 9.2 Avionics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| FMS database update | 28 days | 0.5 hr | 1 technician |
| Pitot-static leak test | 24 months | 4.0 hr | 1 technician |
| ADIRU accuracy check | 12 months | 2.0 hr | 1 technician |
| VOR/ILS accuracy check | 12 months | 2.0 hr | 1 technician |
| BITE fault log review | Weekly | 0.5 hr | 1 technician |
| Antenna inspection | A-check | 1.0 hr | 1 mechanic |

### 9.3 Hydraulics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fluid level check | Daily | 0.25 hr | 1 mechanic |
| Fluid sampling and analysis | 600 FH | 0.5 hr | 1 mechanic |
| System filter replacement | 1,200 FH | 2.0 hr | 1 mechanic |
| EDP inspection | A-check | 2.0 hr | 1 mechanic |
| ACMP functional test | A-check | 1.0 hr | 1 mechanic |
| Actuator inspection | C-check | 6.0 hr | 2 mechanics |
| System pressure test | 24 months | 4.0 hr | 2 mechanics |

### 9.4 Common Task Cards

#### Task Card: ENG-TC-001 - Engine Oil Service

**Purpose:** Replenish engine oil to proper level

**Tools Required:**
- Oil dispenser with flexible spout
- Calibrated dipstick (P/N: GE-TOOL-001)
- Lint-free wipes

**Procedure:**
1. Ensure engine has been shut down for minimum 15 minutes (oil drain-back)
2. Open fan cowl oil service door
3. Remove oil tank cap and check level on integral sight glass
4. Add approved oil (MIL-PRF-23699) if level below ADD mark
5. Do not overfill - level should be between ADD and FULL
6. Replace cap and verify secure
7. Close service door
8. Record quantity added in aircraft log

**Oil Type:** MIL-PRF-23699 (Mobil Jet Oil II or equivalent)

#### Task Card: HYD-TC-001 - Hydraulic Fluid Sample

**Purpose:** Obtain fluid sample for contamination analysis

**Reference:** AMM 29-00-00

**Tools Required:**
- Sample bottle (clean, dry, 100ml minimum)
- Sample valve adapter (P/N: HYD-TOOL-100)
- Gloves and safety glasses

**Procedure:**
1. Ensure hydraulic system depressurized
2. Locate sample port on reservoir (avionics bay)
3. Clean area around sample port
4. Connect adapter and open sample valve
5. Discard first 50ml (flush line)
6. Collect 100ml sample in clean bottle
7. Close valve and disconnect adapter
8. Label sample: Aircraft reg, system (Left/Right), date, hours
9. Submit to approved laboratory within 48 hours

---

## 10. Appendices

### 10.1 Quick Reference - Normal Operating Limits

#### Engine Parameters (CF34-10E)

<!-- BEGIN GENERATED: quick-ref-engine -->
| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) | Max Continuous | Takeoff (5 min) |
|-----------|-------------|-------------|-----------------------|----------------|-----------------|
| N1Speed (%) | 22-28 | 28-35 | 87 (85-89) | 96 | 100 |
| EGT (°C) | 330-400 | 400-460 | 641 (< 661) | < 840 | < 870 |
| FuelFlow (kg/s) | 0.08-0.15 | 0.15-0.22 | 0.27 (0.25-0.29) | 0.75-0.95 | 1.00-1.20 |
| Oil Pressure (psi) | 35-60 | 40-70 | — | 45-75 | 45-75 |
| Oil Temperature (°C) | 50-90 | 60-120 | — | 80-140 | 80-155 |
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

**Fluid temperature:** The Left, Right, and Standby systems each operate from -40 to +107°C.

### 10.2 Abbreviations and Acronyms

| Abbreviation | Definition |
|--------------|------------|
| ACMP | AC Motor Pump |
| ADIRU | Air Data / Inertial Reference Unit |
| AGB | Accessory Gearbox |
| AMM | Aircraft Maintenance Manual |
| BITE | Built-In Test Equipment |
| CDU | Control Display Unit |
| CMC | Central Maintenance Computer |
| EDP | Engine-Driven Pump |
| EEC | Electronic Engine Control |
| EFIS | Electronic Flight Instrument System |
| EICAS | Engine Indication and Crew Alerting System |
| EGT | Exhaust Gas Temperature |
| FADEC | Full Authority Digital Engine Control |
| FH | Flight Hours |
| FMS | Flight Management System |
| FMV | Fuel Metering Value |
| FOD | Foreign Object Damage |
| HMU | Hydromechanical Unit |
| HPC | High Pressure Compressor |
| HPT | High Pressure Turbine |
| LPT | Low Pressure Turbine |
| LRU | Line Replaceable Unit |
| MCD | Magnetic Chip Detector |
| MCT | Maximum Continuous Thrust |
| MEL | Minimum Equipment List |
| MMR | Multi-Mode Receiver |
| NAV | Navigation |
| QAR | Quick Access Recorder |
| SOAP | Spectrometric Oil Analysis Program |
| VSV | Variable Stator Vane |

### 10.3 Reference Documents

| Document | Number | Description |
|----------|--------|-------------|
| Aircraft Maintenance Manual | AMM E190 | Primary maintenance reference |
| Fault Isolation Manual | FIM E190 | Troubleshooting guidance |
| Illustrated Parts Catalog | IPC E190 | Parts identification |
| Component Maintenance Manual | CMM CF34-10E | Engine overhaul data |
| Service Bulletin Index | SB E190 | Modification tracking |
| Airworthiness Directives | AD List | Mandatory compliance |
| Master Minimum Equipment List | MMEL E190 | Dispatch deviations |

### 10.4 Emergency Contacts

| Function | Contact | Availability |
|----------|---------|--------------|
| AOG Desk | +1-800-555-0190 | 24/7 |
| Engine Support (GE Aviation) | +1-513-555-0134 | 24/7 |
| Embraer Technical Support | +1-954-555-0100 | 24/7 |
| Technical Records | tech.records@exampleair.com | 24/7 |
| Engineering Support | engineering@exampleair.com | 24/7 |
| Parts Supply | parts@exampleair.com | 24/7 |

### 10.5 Fleet Maintenance Statistics

<!-- BEGIN GENERATED: fleet-statistics -->
These figures are counts from this demo's generated fleet data: 30 aircraft over 90 days, seed 42. The E190 has 10 of the aircraft and 74 of the maintenance events.

**Events by Severity:**

| Severity | Events | Share |
|----------|--------|-------|
| Critical | 16 | 22% |
| Major | 23 | 31% |
| Minor | 35 | 47% |

**Events by System:**

| System | Events | Share |
|--------|--------|-------|
| Engine | 48 | 65% |
| Avionics | 15 | 20% |
| Hydraulics | 11 | 15% |

**Events by Fault:**

| Fault | System | Events | Share |
|-------|--------|--------|-------|
| Overheat | Engine | 15 | 20% |
| Bearing wear | Engine | 12 | 16% |
| Sensor drift | Engine | 10 | 14% |
| Electrical fault | Avionics | 10 | 14% |
| Leak | Hydraulics | 9 | 12% |
| Sensor drift | Avionics | 5 | 7% |
| Leak | Engine | 4 | 5% |
| Vibration exceedance | Engine | 4 | 5% |
| Contamination | Engine | 3 | 4% |
| Contamination | Hydraulics | 2 | 3% |
<!-- END GENERATED: fleet-statistics -->

### 10.6 Revision History Log

| Page | Rev | Date | Change Description |
|------|-----|------|--------------------|
| All | 1.0 | 2024-10-01 | Initial release |

---

**END OF DOCUMENT**

*This manual is for demonstration purposes. Always refer to official Embraer documentation for actual maintenance procedures.*
