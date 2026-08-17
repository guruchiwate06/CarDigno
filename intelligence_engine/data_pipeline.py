"""
CarDigno - Telemetry Data Pipeline & Feature Engineering
Queries time-series telemetry from SQLite WAL storage, performs pivoting and forward-fill imputation,
and computes 10-second rolling window feature vectors (EMA smoothing, Air Intake Ratio, Thermal Derivative).
"""

import collections
import logging
import os
import sqlite3
from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np
import pandas as pd

logger = logging.getLogger("DataPipeline")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "telemetry.db"
)

# Standard metrics expected from SAE J1979 OBD-II ingestion
STANDARD_METRICS = ["RPM", "Coolant_Temp", "MAF", "Fuel_Level"]

# Feature columns output for Machine Learning anomaly detection
FEATURE_COLUMNS = [
    "rpm_ema",
    "maf_ema",
    "temp_ema",
    "air_intake_ratio",
    "dtemp_dt",
    "rpm_std_10s",
    "maf_std_10s",
    "temp_max_10s",
]


class TelemetryDataPipeline:
    """
    Batch feature engineering pipeline for historical and windowed vehicular telemetry.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def load_telemetry_from_db(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Queries raw telemetry logs from SQLite storage into a pandas DataFrame.
        """
        if not os.path.exists(self.db_path):
            logger.warning(f"Database path '{self.db_path}' does not exist.")
            return pd.DataFrame(columns=["id", "timestamp", "pid", "metric_name", "decoded_value", "unit"])

        query = "SELECT timestamp, metric_name, decoded_value FROM telemetry_logs"
        conditions = []
        params: List[Any] = []

        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(float(start_time))
        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(float(end_time))

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            df = pd.read_sql_query(query, conn, params=params)
        finally:
            conn.close()

        return df

    @staticmethod
    def clean_and_pivot_telemetry(raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans and pivots raw time-series telemetry rows on timestamp.
        Applies forward-fill (.ffill()) and backward-fill (.bfill()) imputation
        to synchronize staggered PID transmission arrivals across 10 Hz cycles.
        """
        if raw_df.empty:
            return pd.DataFrame(columns=["timestamp"] + STANDARD_METRICS)

        # Ensure correct datatypes
        df = raw_df.copy()
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df["decoded_value"] = pd.to_numeric(df["decoded_value"], errors="coerce")
        df = df.dropna(subset=["timestamp", "metric_name", "decoded_value"])

        # Deduplicate multiple readings for same metric at exact timestamp
        df = df.drop_duplicates(subset=["timestamp", "metric_name"], keep="last")

        # Pivot table: timestamps as rows, metric names as columns
        pivoted = df.pivot(index="timestamp", columns="metric_name", values="decoded_value")
        pivoted = pivoted.sort_index()

        # Ensure all standard columns exist
        for col in STANDARD_METRICS:
            if col not in pivoted.columns:
                pivoted[col] = np.nan

        # Impute missing values across high-frequency tick gaps
        pivoted = pivoted.ffill().bfill()

        # Reset index to have 'timestamp' as a standard column
        cleaned = pivoted.reset_index()
        return cleaned

    @staticmethod
    def compute_rolling_features(
        cleaned_df: pd.DataFrame,
        window_samples: int = 100,
        ema_span: int = 20
    ) -> pd.DataFrame:
        """
        Computes 10-second rolling window feature vectors:
        - Exponential Moving Average (EMA) smoothing for Engine RPM and MAF rate (removes sensor noise).
        - Air Intake Ratio: (MAF / RPM) volumetric efficiency feature.
        - Thermal Derivative: (dTemp / dt) rate of temperature change over time.
        - 10-second rolling standard deviation (RPM stability, MAF stability) and max temperature.
        """
        if cleaned_df.empty:
            return pd.DataFrame(columns=["timestamp"] + STANDARD_METRICS + FEATURE_COLUMNS)

        df = cleaned_df.copy().sort_values("timestamp").reset_index(drop=True)

        # 1. EMA smoothing (span=20 samples ≈ 2 seconds at 10 Hz for noise filtering)
        df["rpm_ema"] = df["RPM"].ewm(span=ema_span, adjust=False).mean()
        df["maf_ema"] = df["MAF"].ewm(span=ema_span, adjust=False).mean()
        df["temp_ema"] = df["Coolant_Temp"].ewm(span=ema_span, adjust=False).mean()
        if "Fuel_Level" in df.columns:
            df["fuel_ema"] = df["Fuel_Level"].ewm(span=ema_span, adjust=False).mean()

        # 2. Air Intake Ratio: (MAF / RPM)
        # Volumetric efficiency metric: ratio of mass air flow (g/s) to engine rotational speed (RPM).
        # A 1e-5 epsilon prevents zero-division during engine shutoff.
        df["air_intake_ratio"] = df["maf_ema"] / (df["rpm_ema"] + 1e-5)

        # 3. Thermal Derivative: (dTemp / dt)
        # Coolant rate of temperature change (°C/s).
        # Calculate time delta between consecutive samples
        time_diff = df["timestamp"].diff()
        # Handle zero or negative time deltas safely
        time_diff = time_diff.apply(lambda x: x if x > 0.001 else 0.1)
        time_diff = time_diff.fillna(0.1)

        # Derivative of smoothed coolant temp with respect to time
        df["dtemp_dt"] = df["temp_ema"].diff() / time_diff
        df["dtemp_dt"] = df["dtemp_dt"].fillna(0.0)

        # 4. 10-Second Rolling Window Statistics (at 10 Hz, window_samples ≈ 100)
        min_periods = max(1, min(10, len(df)))
        df["rpm_std_10s"] = df["RPM"].rolling(window=window_samples, min_periods=min_periods).std().fillna(0.0)
        df["maf_std_10s"] = df["MAF"].rolling(window=window_samples, min_periods=min_periods).std().fillna(0.0)
        df["temp_max_10s"] = df["Coolant_Temp"].rolling(window=window_samples, min_periods=min_periods).max().fillna(df["Coolant_Temp"])

        return df

    def process_pipeline(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Executes end-to-end batch pipeline: Load -> Clean & Pivot -> Compute Features.
        """
        raw_df = self.load_telemetry_from_db(start_time=start_time, end_time=end_time, limit=limit)
        if raw_df.empty:
            return pd.DataFrame(columns=["timestamp"] + STANDARD_METRICS + FEATURE_COLUMNS)

        cleaned_df = self.clean_and_pivot_telemetry(raw_df)
        feature_df = self.compute_rolling_features(cleaned_df)
        return feature_df


class OnlineFeaturePipeline:
    """
    Real-time rolling feature extractor maintaining an in-memory buffer
    for single-frame streaming inference at 10 Hz without querying SQLite repeatedly.
    """

    def __init__(self, buffer_size: int = 150, ema_alpha: float = 0.1):
        self.buffer_size = buffer_size
        self.ema_alpha = ema_alpha  # smoothing factor (0.1 ~ span=19)
        
        # State registers
        self.latest_state: Dict[str, float] = {
            "RPM": 800.0,
            "Coolant_Temp": 85.0,
            "MAF": 3.2,
            "Fuel_Level": 88.0,
        }
        
        # Smoothed state registers
        self.rpm_ema = 800.0
        self.maf_ema = 3.2
        self.temp_ema = 85.0
        self.fuel_ema = 88.0
        
        self.last_timestamp: Optional[float] = None
        self.last_temp_ema: float = 85.0
        self.dtemp_dt: float = 0.0
        
        # Rolling deques for window statistics
        self.rpm_history = collections.deque(maxlen=buffer_size)
        self.maf_history = collections.deque(maxlen=buffer_size)
        self.temp_history = collections.deque(maxlen=buffer_size)

    def update_single_metric(self, timestamp: float, metric_name: str, value: float) -> Optional[Dict[str, float]]:
        """
        Ingests a single decoded OBD-II PID metric and updates state.
        Returns the updated feature vector if a valid metric was processed.
        """
        if metric_name not in self.latest_state:
            return None

        self.latest_state[metric_name] = float(value)
        return self._compute_latest_features(timestamp)

    def update_snapshot(self, timestamp: float, snapshot: Dict[str, float]) -> Dict[str, float]:
        """
        Ingests a full vehicle state snapshot and updates feature vector.
        """
        for k, v in snapshot.items():
            if k in self.latest_state:
                self.latest_state[k] = float(v)
        return self._compute_latest_features(timestamp)

    def _compute_latest_features(self, timestamp: float) -> Dict[str, float]:
        """Calculates latest online feature vector."""
        rpm = self.latest_state["RPM"]
        maf = self.latest_state["MAF"]
        temp = self.latest_state["Coolant_Temp"]
        fuel = self.latest_state["Fuel_Level"]

        # Update EMA
        self.rpm_ema = (self.ema_alpha * rpm) + ((1.0 - self.ema_alpha) * self.rpm_ema)
        self.maf_ema = (self.ema_alpha * maf) + ((1.0 - self.ema_alpha) * self.maf_ema)
        self.temp_ema = (self.ema_alpha * temp) + ((1.0 - self.ema_alpha) * self.temp_ema)
        self.fuel_ema = (self.ema_alpha * fuel) + ((1.0 - self.ema_alpha) * self.fuel_ema)

        # Update history
        self.rpm_history.append(rpm)
        self.maf_history.append(maf)
        self.temp_history.append(temp)

        # Thermal derivative
        if self.last_timestamp is not None:
            dt = max(0.001, timestamp - self.last_timestamp)
            self.dtemp_dt = (self.temp_ema - self.last_temp_ema) / dt
        else:
            self.dtemp_dt = 0.0

        self.last_timestamp = timestamp
        self.last_temp_ema = self.temp_ema

        # Air intake ratio
        air_intake_ratio = self.maf_ema / (self.rpm_ema + 1e-5)

        # Window statistics
        rpm_std = float(np.std(self.rpm_history)) if len(self.rpm_history) > 1 else 0.0
        maf_std = float(np.std(self.maf_history)) if len(self.maf_history) > 1 else 0.0
        temp_max = float(np.max(self.temp_history)) if len(self.temp_history) > 0 else temp

        return {
            "timestamp": timestamp,
            "RPM": rpm,
            "Coolant_Temp": temp,
            "MAF": maf,
            "Fuel_Level": fuel,
            "rpm_ema": self.rpm_ema,
            "maf_ema": self.maf_ema,
            "temp_ema": self.temp_ema,
            "fuel_ema": self.fuel_ema,
            "air_intake_ratio": air_intake_ratio,
            "dtemp_dt": self.dtemp_dt,
            "rpm_std_10s": rpm_std,
            "maf_std_10s": maf_std,
            "temp_max_10s": temp_max,
        }
