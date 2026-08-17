"""
CarDigno - Unsupervised Isolation Forest Anomaly Detection
Detects vehicular subsystem anomalies and multidimensional sensor drift using scikit-learn Isolation Forest.
Saves, loads, and trains model pipeline artifacts for real-time telemetry scoring.
"""

import logging
import os
import joblib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from intelligence_engine.data_pipeline import (
    FEATURE_COLUMNS,
    TelemetryDataPipeline,
)

logger = logging.getLogger("AnomalyDetector")

# Default path for serialized model artifacts
DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "models"
)
DEFAULT_MODEL_PATH = os.path.join(DEFAULT_MODEL_DIR, "isolation_forest.pkl")


class TelemetryAnomalyDetector:
    """
    Unsupervised ML Anomaly Detector for high-frequency vehicular telemetry.
    Uses Isolation Forest with feature scaling on 10-second rolling windows.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        contamination: float = 0.05,
        n_estimators: int = 100,
        random_state: int = 42
    ):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.pipeline: Optional[Pipeline] = None
        self.feature_columns = list(FEATURE_COLUMNS)
        self.is_fitted = False

        # Attempt to load model artifact if exists
        if os.path.exists(self.model_path):
            self.load(self.model_path)

    def _build_pipeline(self) -> Pipeline:
        """Constructs the scikit-learn feature scaling and Isolation Forest pipeline."""
        return Pipeline([
            ("scaler", StandardScaler()),
            (
                "model",
                IsolationForest(
                    n_estimators=self.n_estimators,
                    contamination=self.contamination,
                    random_state=self.random_state,
                    n_jobs=-1,
                ),
            ),
        ])

    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> "TelemetryAnomalyDetector":
        """
        Fits the Isolation Forest pipeline on baseline normal driving feature vectors.
        """
        if isinstance(X, pd.DataFrame):
            # Extract only expected feature columns
            missing_cols = [c for c in self.feature_columns if c not in X.columns]
            if missing_cols:
                raise ValueError(f"Input DataFrame is missing required feature columns: {missing_cols}")
            X_mat = X[self.feature_columns].values
        else:
            X_mat = np.asarray(X)

        if X_mat.shape[0] < 10:
            raise ValueError(f"Insufficient training samples ({X_mat.shape[0]}). Need at least 10 samples.")

        logger.info(f"Training Isolation Forest model on {X_mat.shape[0]} feature windows with {X_mat.shape[1]} features...")
        self.pipeline = self._build_pipeline()
        self.pipeline.fit(X_mat)
        self.is_fitted = True
        logger.info("Isolation Forest model training complete.")
        return self

    def predict(
        self,
        X: Union[pd.DataFrame, np.ndarray, Dict[str, float]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Evaluates input feature vectors.
        
        Returns:
            Tuple of (anomaly_flags, decision_scores)
            - anomaly_flags: array of int (1 = Normal, -1 = Anomaly)
            - decision_scores: array of float (higher = more normal, lower/negative = anomaly)
        """
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("AnomalyDetector model is not fitted. Train or load a model first.")

        X_mat = self._prepare_input_matrix(X)
        anomaly_flags = self.pipeline.predict(X_mat)
        # decision_function returns average anomaly score of base estimators.
        # Positive values denote inliers/normal, negative values denote outliers/anomalies.
        decision_scores = self.pipeline.decision_function(X_mat)

        return anomaly_flags, decision_scores

    def evaluate_sample(self, features: Dict[str, float]) -> Dict[str, Any]:
        """
        Convenience method for real-time single-sample telemetry evaluation.
        
        Returns dictionary with:
            - is_anomaly (bool): True if flagged anomalous (-1)
            - anomaly_flag (int): 1 (normal) or -1 (anomaly)
            - decision_score (float): raw decision score from Isolation Forest
            - anomaly_score (float): normalized anomaly score in [0.0, 1.0] (higher = more severe anomaly)
        """
        flags, scores = self.predict(features)
        flag = int(flags[0])
        score = float(scores[0])

        # Normalize score into [0.0, 1.0] where 0.0 is completely normal and 1.0 is severe anomaly
        # Typically Isolation Forest decision_function ranges roughly from -0.35 to +0.25
        # We map score > 0 -> anomaly_score < 0.3; score < 0 -> anomaly_score > 0.5
        normalized_anomaly = float(1.0 / (1.0 + np.exp(score * 8.0)))

        return {
            "is_anomaly": (flag == -1),
            "anomaly_flag": flag,
            "decision_score": score,
            "anomaly_score": round(normalized_anomaly, 4),
        }

    def _prepare_input_matrix(self, X: Union[pd.DataFrame, np.ndarray, Dict[str, float]]) -> np.ndarray:
        """Converts diverse input types into standard NumPy feature matrix."""
        if isinstance(X, dict):
            row = []
            for col in self.feature_columns:
                if col not in X:
                    raise KeyError(f"Feature '{col}' missing from input dictionary.")
                row.append(float(X[col]))
            return np.array([row], dtype=np.float64)

        elif isinstance(X, pd.DataFrame):
            missing_cols = [c for c in self.feature_columns if c not in X.columns]
            if missing_cols:
                raise ValueError(f"Input DataFrame is missing required feature columns: {missing_cols}")
            return X[self.feature_columns].to_numpy(dtype=np.float64)

        else:
            arr = np.asarray(X, dtype=np.float64)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] != len(self.feature_columns):
                raise ValueError(
                    f"Feature dimension mismatch: expected {len(self.feature_columns)} features, got {arr.shape[1]}."
                )
            return arr

    def save(self, path: Optional[str] = None) -> str:
        """Serializes the trained pipeline to disk."""
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Cannot save an unfitted model.")

        save_path = path or self.model_path
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        joblib.dump(
            {
                "pipeline": self.pipeline,
                "feature_columns": self.feature_columns,
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
                "random_state": self.random_state,
            },
            save_path,
        )
        logger.info(f"Saved Isolation Forest model artifact to '{save_path}'")
        return save_path

    def load(self, path: Optional[str] = None) -> "TelemetryAnomalyDetector":
        """Loads serialized model pipeline artifact from disk."""
        load_path = path or self.model_path
        if not os.path.exists(load_path):
            raise FileNotFoundError(f"Model file not found at '{load_path}'")

        artifact = joblib.load(load_path)
        self.pipeline = artifact["pipeline"]
        self.feature_columns = artifact.get("feature_columns", self.feature_columns)
        self.contamination = artifact.get("contamination", self.contamination)
        self.is_fitted = True
        logger.info(f"Loaded Isolation Forest model artifact from '{load_path}'")
        return self

    @classmethod
    def train_baseline_model(
        cls,
        save_path: Optional[str] = None,
        duration_seconds: float = 300.0,
        rate_hz: float = 10.0
    ) -> "TelemetryAnomalyDetector":
        """
        Generates synthetic normal driving telemetry cycles, computes rolling window features,
        trains the Isolation Forest model, and saves the artifact.
        """
        try:
            from simulator.elm327_mock import VehiclePhysicsSimulator
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from simulator.elm327_mock import VehiclePhysicsSimulator

        logger.info(f"Generating {duration_seconds}s of normal driving telemetry for baseline training...")
        sim = VehiclePhysicsSimulator(inject_anomaly=False)
        
        # Collect normal simulation history
        total_steps = int(duration_seconds * rate_hz)
        records = []
        t = 0.0
        dt = 1.0 / rate_hz

        for _ in range(total_steps):
            state = sim.update()
            # Staggered emission simulation matching OBD-II polling
            records.append({"timestamp": t + 0.00, "metric_name": "RPM", "decoded_value": state["rpm"]})
            records.append({"timestamp": t + 0.02, "metric_name": "Coolant_Temp", "decoded_value": state["coolant_temp"]})
            records.append({"timestamp": t + 0.04, "metric_name": "MAF", "decoded_value": state["maf"]})
            records.append({"timestamp": t + 0.06, "metric_name": "Fuel_Level", "decoded_value": state["fuel_level"]})
            t += dt

        raw_df = pd.DataFrame(records)
        cleaned_df = TelemetryDataPipeline.clean_and_pivot_telemetry(raw_df)
        feature_df = TelemetryDataPipeline.compute_rolling_features(cleaned_df)

        detector = cls(model_path=save_path)
        detector.fit(feature_df)
        detector.save(save_path)
        return detector
