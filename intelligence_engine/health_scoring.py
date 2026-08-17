"""
CarDigno - Subsystem Health Degradation & Diagnostic Trouble Code (DTC) Engine
Translates continuous ML anomaly scores and physics telemetry into 0–100% subsystem health ratings
and triggers standardized SAE J2012 OBD-II Diagnostic Trouble Codes when health drops below 60%.
"""

import logging
from typing import Dict, List, Optional, Any, Union
import numpy as np

logger = logging.getLogger("HealthEngine")


class DiagnosticTroubleCode:
    """Standardized OBD-II Diagnostic Trouble Code representation."""

    def __init__(
        self,
        code: str,
        subsystem: str,
        severity: str,
        description: str,
        recommended_action: str
    ):
        self.code = code
        self.subsystem = subsystem
        self.severity = severity  # "INFO", "WARNING", "CRITICAL"
        self.description = description
        self.recommended_action = recommended_action

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "subsystem": self.subsystem,
            "severity": self.severity,
            "description": self.description,
            "recommended_action": self.recommended_action,
        }


# Standard SAE J2012 DTC Definitions for CarDigno
DTC_CATALOG = {
    "P0117": DiagnosticTroubleCode(
        code="P0117",
        subsystem="Thermal",
        severity="CRITICAL",
        description="Engine Coolant Temperature Circuit Low / Severe Overheating (>115°C)",
        recommended_action="Safely pull over and inspect cooling system, radiator, coolant level, and thermostat immediately."
    ),
    "P0217": DiagnosticTroubleCode(
        code="P0217",
        subsystem="Thermal",
        severity="CRITICAL",
        description="Engine Coolant Overtemperature Condition",
        recommended_action="Shut down engine to prevent cylinder head warpage and blown head gasket."
    ),
    "P0101": DiagnosticTroubleCode(
        code="P0101",
        subsystem="Air_Intake",
        severity="WARNING",
        description="Mass or Volume Air Flow (MAF) Circuit Range/Performance Problem",
        recommended_action="Inspect MAF sensor wiring, clean air filter, and check for intake manifold vacuum leaks."
    ),
    "P0171": DiagnosticTroubleCode(
        code="P0171",
        subsystem="Air_Intake",
        severity="WARNING",
        description="System Too Lean (Bank 1) - Excessive Air or Insufficient Fuel Delivery",
        recommended_action="Check fuel pressure, fuel injectors, and inspect for unmetered air leaks."
    ),
    "P0300": DiagnosticTroubleCode(
        code="P0300",
        subsystem="Ignition_Combustion",
        severity="WARNING",
        description="Random/Multiple Cylinder Misfire Detected",
        recommended_action="Inspect spark plugs, ignition coils, and fuel injectors for intermittent misfire."
    ),
}


class DiagnosticTroubleCodeEngine:
    """
    Evaluates subsystem health ratings and physical thresholds to determine active DTC alerts.
    """

    CRITICAL_HEALTH_THRESHOLD = 60.0  # DTCs trigger when health drops below 60%

    @classmethod
    def evaluate_dtcs(
        cls,
        thermal_health: float,
        air_intake_health: float,
        features: Dict[str, float],
        anomaly_flag: int = 1
    ) -> List[Dict[str, str]]:
        """
        Evaluates active diagnostic trouble codes based on subsystem health and physical sensor readings.
        """
        active_codes: List[DiagnosticTroubleCode] = []
        coolant_temp = features.get("Coolant_Temp", features.get("temp_ema", 85.0))
        temp_max = features.get("temp_max_10s", coolant_temp)
        air_ratio = features.get("air_intake_ratio", 0.005)
        rpm_std = features.get("rpm_std_10s", 0.0)

        # 1. Thermal Subsystem DTC Rules
        if thermal_health < cls.CRITICAL_HEALTH_THRESHOLD or coolant_temp >= 115.0 or temp_max >= 115.0:
            active_codes.append(DTC_CATALOG["P0117"])
            if coolant_temp >= 120.0 or temp_max >= 120.0:
                active_codes.append(DTC_CATALOG["P0217"])

        # 2. Air Intake & Volumetric Ratio Rules
        if air_intake_health < cls.CRITICAL_HEALTH_THRESHOLD:
            active_codes.append(DTC_CATALOG["P0101"])
            # If air ratio is abnormally high or low, add lean/rich DTC
            if air_ratio > 0.012 or air_ratio < 0.0015:
                active_codes.append(DTC_CATALOG["P0171"])

        # 3. Combustion / Misfire Rules (High RPM instability / variance)
        if rpm_std > 250.0 and anomaly_flag == -1:
            active_codes.append(DTC_CATALOG["P0300"])

        # Deduplicate active codes
        seen = set()
        unique_dtcs = []
        for dtc in active_codes:
            if dtc.code not in seen:
                seen.add(dtc.code)
                unique_dtcs.append(dtc.to_dict())

        return unique_dtcs


class SubsystemHealthEngine:
    """
    Computes 0–100% degradation ratings for Thermal and Air Intake subsystems
    by combining physics thresholds with ML decision scores.
    """

    def __init__(self, dtc_threshold: float = 60.0):
        self.dtc_threshold = dtc_threshold
        self.dtc_engine = DiagnosticTroubleCodeEngine()

    def compute_thermal_health(
        self,
        features: Dict[str, float],
        anomaly_score: float = 0.0
    ) -> float:
        """
        Calculates Thermal Subsystem Health (0% to 100%).
        
        Physics Baseline:
        - 80°C - 92°C: Optimal operating window -> 100%
        - 93°C - 105°C: Elevated temperature -> 95% down to 70%
        - 106°C - 114°C: Thermal distress -> 69% down to 60%
        - >= 115°C: Critical Overheating -> drops sharply < 50% down to 10%
        
        Thermal Derivative Penalties:
        - dTemp/dt > 0.5 °C/s: Rapid heating penalty
        - dTemp/dt > 1.0 °C/s: Thermal shock penalty
        """
        temp = features.get("Coolant_Temp", features.get("temp_ema", 85.0))
        temp_max = features.get("temp_max_10s", temp)
        dtemp_dt = features.get("dtemp_dt", 0.0)

        # Baseline thermal score from temperature
        effective_temp = max(temp, temp_max)
        
        if effective_temp <= 92.0:
            base_health = 100.0
        elif effective_temp <= 105.0:
            # Linear decay from 100% at 92°C to 70% at 105°C
            base_health = 100.0 - ((effective_temp - 92.0) / (105.0 - 92.0)) * 30.0
        elif effective_temp < 115.0:
            # Linear decay from 70% at 105°C to 60% at 114.9°C
            base_health = 70.0 - ((effective_temp - 105.0) / (115.0 - 105.0)) * 10.0
        elif effective_temp < 125.0:
            # Critical drop: 50% at 115°C down to 15% at 125°C
            base_health = 50.0 - ((effective_temp - 115.0) / (125.0 - 115.0)) * 35.0
        else:
            # Catastrophic overheat > 125°C
            base_health = max(5.0, 15.0 - (effective_temp - 125.0) * 2.0)

        # Dynamic thermal runaway derivative penalty
        if dtemp_dt > 1.0:
            base_health -= min(25.0, dtemp_dt * 15.0)
        elif dtemp_dt > 0.4:
            base_health -= min(15.0, dtemp_dt * 10.0)

        # ML Anomaly penalty (scaled if anomaly is severe)
        if anomaly_score > 0.6:
            base_health -= (anomaly_score - 0.6) * 25.0

        return float(np.clip(base_health, 0.0, 100.0))

    def compute_air_intake_health(
        self,
        features: Dict[str, float],
        anomaly_score: float = 0.0
    ) -> float:
        """
        Calculates Air Intake Subsystem Health (0% to 100%).
        
        Evaluates:
        - Air intake ratio (MAF / RPM) volumetric efficiency.
        - MAF sensor variance / turbulence (maf_std_10s).
        - ML Anomaly score contribution.
        """
        air_ratio = features.get("air_intake_ratio", 0.004)
        maf = features.get("MAF", features.get("maf_ema", 3.2))
        maf_std = features.get("maf_std_10s", 0.0)
        rpm = features.get("RPM", features.get("rpm_ema", 800.0))

        # Expected ratio typically around 0.0035 - 0.0080
        if 0.0030 <= air_ratio <= 0.0085:
            base_health = 100.0
        elif 0.0020 <= air_ratio < 0.0030 or 0.0085 < air_ratio <= 0.0110:
            base_health = 80.0
        elif 0.0010 <= air_ratio < 0.0020 or 0.0110 < air_ratio <= 0.0150:
            base_health = 55.0  # Degraded (< 60%)
        else:
            base_health = 30.0  # Severe intake leak or sensor failure

        # MAF instability penalty (excessive turbulence or sensor noise)
        if maf_std > 8.0:
            base_health -= min(30.0, (maf_std - 8.0) * 3.0)
        elif maf_std > 4.0:
            base_health -= min(15.0, (maf_std - 4.0) * 2.0)

        # MAF absolute bounds check
        if maf < 0.5 and rpm > 500.0:
            base_health = min(base_health, 20.0)  # MAF drop out

        # ML Anomaly contribution
        if anomaly_score > 0.6:
            base_health -= (anomaly_score - 0.6) * 20.0

        return float(np.clip(base_health, 0.0, 100.0))

    def evaluate_health(
        self,
        features: Dict[str, float],
        anomaly_score: float = 0.0,
        anomaly_flag: int = 1
    ) -> Dict[str, Any]:
        """
        Comprehensive health evaluation returning subsystem ratings, overall vehicular health,
        and triggered Diagnostic Trouble Codes (DTCs).
        """
        thermal_health = round(self.compute_thermal_health(features, anomaly_score), 2)
        air_health = round(self.compute_air_intake_health(features, anomaly_score), 2)

        # Overall health is weighted combination of subsystems and ML score
        ml_health_weight = max(0.0, 100.0 - (anomaly_score * 100.0))
        overall_health = round(
            (thermal_health * 0.45) + (air_health * 0.40) + (ml_health_weight * 0.15),
            2
        )
        overall_health = float(np.clip(overall_health, 0.0, 100.0))

        # Active DTCs
        active_dtcs = self.dtc_engine.evaluate_dtcs(
            thermal_health=thermal_health,
            air_intake_health=air_health,
            features=features,
            anomaly_flag=anomaly_flag
        )

        return {
            "timestamp": features.get("timestamp", 0.0),
            "overall_health": overall_health,
            "thermal_health": thermal_health,
            "air_intake_health": air_health,
            "is_anomaly": (anomaly_flag == -1 or len(active_dtcs) > 0),
            "anomaly_score": round(anomaly_score, 4),
            "anomaly_flag": anomaly_flag,
            "active_dtcs": active_dtcs,
            "status": "CRITICAL" if overall_health < 50.0 else ("WARNING" if overall_health < 75.0 else "HEALTHY"),
        }
