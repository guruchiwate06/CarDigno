"""
CarDigno - Intelligence Engine & Anomaly Detection Unit & Integration Tests
Tests data pipeline, rolling window feature extraction, Isolation Forest anomaly scoring,
subsystem degradation health ratings, and automatic DTC triggers.
"""

import os
import shutil
import tempfile
import time
import unittest
import numpy as np
import pandas as pd

from simulator.elm327_mock import VehiclePhysicsSimulator
from telemetry_core.db_logger import TelemetryLogger
from intelligence_engine.data_pipeline import (
    TelemetryDataPipeline,
    OnlineFeaturePipeline,
    FEATURE_COLUMNS,
)
from intelligence_engine.anomaly_detector import TelemetryAnomalyDetector
from intelligence_engine.health_scoring import (
    SubsystemHealthEngine,
    DiagnosticTroubleCodeEngine,
    DTC_CATALOG,
)


import gc

class TestDataPipeline(unittest.TestCase):
    """Unit tests for TelemetryDataPipeline and OnlineFeaturePipeline."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_telemetry.db")
        self.logger = TelemetryLogger(db_path=self.db_path)
        self.pipeline = TelemetryDataPipeline(db_path=self.db_path)

    def tearDown(self):
        if hasattr(self, "logger") and self.logger:
            self.logger.close()
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_clean_and_pivot_telemetry(self):
        """Verifies pivoting and forward-fill imputation on staggered metric arrivals."""
        # Simulated staggered arrivals
        records = [
            {"timestamp": 100.0, "pid": "010C", "metric_name": "RPM", "decoded_value": 800.0, "unit": "RPM"},
            {"timestamp": 100.1, "pid": "0105", "metric_name": "Coolant_Temp", "decoded_value": 85.0, "unit": "°C"},
            {"timestamp": 100.2, "pid": "0110", "metric_name": "MAF", "decoded_value": 3.2, "unit": "g/s"},
            {"timestamp": 100.3, "pid": "012F", "metric_name": "Fuel_Level", "decoded_value": 88.0, "unit": "%"},
            {"timestamp": 101.0, "pid": "010C", "metric_name": "RPM", "decoded_value": 850.0, "unit": "RPM"},
            {"timestamp": 101.1, "pid": "0105", "metric_name": "Coolant_Temp", "decoded_value": 85.5, "unit": "°C"},
        ]
        self.logger.log_batch(records)

        raw_df = self.pipeline.load_telemetry_from_db()
        self.assertEqual(len(raw_df), 6)

        pivoted_df = self.pipeline.clean_and_pivot_telemetry(raw_df)
        self.assertIn("RPM", pivoted_df.columns)
        self.assertIn("Coolant_Temp", pivoted_df.columns)
        self.assertIn("MAF", pivoted_df.columns)
        self.assertIn("Fuel_Level", pivoted_df.columns)
        # Check no NaN values after forward & backward fill
        self.assertFalse(pivoted_df.isnull().values.any())

    def test_compute_rolling_features(self):
        """Verifies EMA smoothing, air intake ratio, and thermal derivative calculations."""
        # Generate synthetic data with noise
        timestamps = np.linspace(10.0, 30.0, 200)
        np.random.seed(42)
        rpm_raw = 2000.0 + np.random.normal(0, 100, 200)
        maf_raw = 12.0 + np.random.normal(0, 1.5, 200)
        # Rising temperature from 85°C to 95°C over 20s -> dTemp/dt ≈ 0.5 °C/s
        temp_raw = 85.0 + 0.5 * (timestamps - 10.0)
        fuel_raw = np.full(200, 75.0)

        cleaned_df = pd.DataFrame({
            "timestamp": timestamps,
            "RPM": rpm_raw,
            "Coolant_Temp": temp_raw,
            "MAF": maf_raw,
            "Fuel_Level": fuel_raw,
        })

        feature_df = self.pipeline.compute_rolling_features(cleaned_df, window_samples=50, ema_span=20)

        for col in FEATURE_COLUMNS:
            self.assertIn(col, feature_df.columns)

        # 1. Verify EMA smoothing reduces variance
        self.assertLess(feature_df["rpm_ema"].std(), pd.Series(rpm_raw).std())
        self.assertLess(feature_df["maf_ema"].std(), pd.Series(maf_raw).std())

        # 2. Verify Air Intake Ratio (MAF / RPM ≈ 12 / 2000 = 0.006)
        mean_air_ratio = feature_df["air_intake_ratio"].mean()
        self.assertAlmostEqual(mean_air_ratio, 12.0 / 2000.0, delta=0.002)

        # 3. Verify Thermal Derivative (dTemp/dt ≈ 0.5 °C/s)
        # Check derivative in the middle of the sequence
        mean_dtemp = feature_df["dtemp_dt"].iloc[10:].mean()
        self.assertAlmostEqual(mean_dtemp, 0.5, delta=0.15)

    def test_online_feature_pipeline(self):
        """Verifies real-time streaming feature calculation via OnlineFeaturePipeline."""
        online = OnlineFeaturePipeline(buffer_size=50)

        t = 1.0
        # Ingest a sequence of state updates (50 steps to reach EMA convergence)
        for i in range(50):
            t += 0.1
            feats = online.update_snapshot(
                timestamp=t,
                snapshot={"RPM": 1500.0, "Coolant_Temp": 90.0, "MAF": 9.0, "Fuel_Level": 80.0}
            )

        self.assertAlmostEqual(feats["rpm_ema"], 1500.0, delta=20.0)
        self.assertAlmostEqual(feats["temp_ema"], 90.0, delta=2.0)
        self.assertAlmostEqual(feats["air_intake_ratio"], 9.0 / 1500.0, delta=0.002)


class TestAnomalyDetector(unittest.TestCase):
    """Unit tests for TelemetryAnomalyDetector."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.model_path = os.path.join(self.temp_dir.name, "test_model.pkl")

    def tearDown(self):
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_fit_save_and_load(self):
        """Tests model fitting, serialization to disk, and deserialization."""
        # Generate dummy normal training data
        np.random.seed(42)
        n_samples = 200
        data = {
            "rpm_ema": np.random.normal(1500, 100, n_samples),
            "maf_ema": np.random.normal(9.0, 1.0, n_samples),
            "temp_ema": np.random.normal(88.0, 2.0, n_samples),
            "air_intake_ratio": np.random.normal(0.006, 0.0005, n_samples),
            "dtemp_dt": np.random.normal(0.02, 0.01, n_samples),
            "rpm_std_10s": np.random.normal(20.0, 5.0, n_samples),
            "maf_std_10s": np.random.normal(0.5, 0.1, n_samples),
            "temp_max_10s": np.random.normal(89.0, 2.0, n_samples),
        }
        train_df = pd.DataFrame(data)

        detector = TelemetryAnomalyDetector(model_path=self.model_path, contamination=0.05)
        detector.fit(train_df)
        self.assertTrue(detector.is_fitted)

        # Save to disk
        saved_path = detector.save()
        self.assertTrue(os.path.exists(saved_path))

        # Load into new instance
        new_detector = TelemetryAnomalyDetector(model_path=self.model_path)
        self.assertTrue(new_detector.is_fitted)

        # Predict with loaded model
        test_sample = {k: float(v[0]) for k, v in data.items()}
        res = new_detector.evaluate_sample(test_sample)
        self.assertIn("is_anomaly", res)
        self.assertIn("anomaly_score", res)
        self.assertIn("decision_score", res)
        # Normal sample should have low anomaly score
        self.assertLess(res["anomaly_score"], 0.7)

    def test_overheat_anomaly_detection(self):
        """Tests that extreme anomalous feature inputs receive high anomaly scores."""
        detector = TelemetryAnomalyDetector.train_baseline_model(
            save_path=self.model_path, duration_seconds=60.0
        )

        # Normal sample (88°C, 1500 RPM, MAF 9.0)
        normal_sample = {
            "rpm_ema": 1500.0,
            "maf_ema": 9.0,
            "temp_ema": 88.0,
            "air_intake_ratio": 0.006,
            "dtemp_dt": 0.01,
            "rpm_std_10s": 25.0,
            "maf_std_10s": 0.4,
            "temp_max_10s": 89.0,
        }
        normal_eval = detector.evaluate_sample(normal_sample)

        # Overheating & thermal runaway sample (128°C, dTemp/dt = 2.5 °C/s)
        overheat_sample = {
            "rpm_ema": 3800.0,
            "maf_ema": 28.0,
            "temp_ema": 128.0,
            "air_intake_ratio": 0.007,
            "dtemp_dt": 2.5,
            "rpm_std_10s": 150.0,
            "maf_std_10s": 3.0,
            "temp_max_10s": 130.0,
        }
        overheat_eval = detector.evaluate_sample(overheat_sample)

        # The overheat anomaly score must be significantly higher than the normal sample
        self.assertGreater(overheat_eval["anomaly_score"], normal_eval["anomaly_score"])


class TestHealthScoringAndDTC(unittest.TestCase):
    """Unit tests for SubsystemHealthEngine and DiagnosticTroubleCodeEngine."""

    def setUp(self):
        self.health_engine = SubsystemHealthEngine()

    def test_healthy_baseline_evaluation(self):
        """Verifies 100% healthy telemetry receives high health scores and 0 DTCs."""
        normal_features = {
            "RPM": 850.0,
            "rpm_ema": 850.0,
            "Coolant_Temp": 88.0,
            "temp_ema": 88.0,
            "temp_max_10s": 89.0,
            "MAF": 3.4,
            "maf_ema": 3.4,
            "air_intake_ratio": 0.004,
            "dtemp_dt": 0.01,
            "rpm_std_10s": 15.0,
            "maf_std_10s": 0.2,
        }

        health_report = self.health_engine.evaluate_health(
            features=normal_features,
            anomaly_score=0.15,
            anomaly_flag=1
        )

        self.assertGreaterEqual(health_report["thermal_health"], 90.0)
        self.assertGreaterEqual(health_report["air_intake_health"], 90.0)
        self.assertGreaterEqual(health_report["overall_health"], 85.0)
        self.assertEqual(len(health_report["active_dtcs"]), 0)
        self.assertEqual(health_report["status"], "HEALTHY")

    def test_overheat_lowers_health_and_triggers_p0117(self):
        """Verifies coolant temp > 115°C drops thermal health below 60% and triggers DTC P0117."""
        overheat_features = {
            "RPM": 2500.0,
            "rpm_ema": 2500.0,
            "Coolant_Temp": 118.5,
            "temp_ema": 118.0,
            "temp_max_10s": 119.0,
            "MAF": 14.0,
            "maf_ema": 14.0,
            "air_intake_ratio": 0.0056,
            "dtemp_dt": 0.8,
            "rpm_std_10s": 30.0,
            "maf_std_10s": 0.5,
        }

        health_report = self.health_engine.evaluate_health(
            features=overheat_features,
            anomaly_score=0.85,
            anomaly_flag=-1
        )

        # Thermal health must drop below 60%
        self.assertLess(health_report["thermal_health"], 60.0)
        self.assertTrue(health_report["is_anomaly"])

        # DTC P0117 must be triggered
        dtc_codes = [d["code"] for d in health_report["active_dtcs"]]
        self.assertIn("P0117", dtc_codes)

    def test_maf_vacuum_leak_triggers_p0101(self):
        """Verifies abnormal air intake ratio degrades air intake health and triggers P0101."""
        maf_leak_features = {
            "RPM": 2000.0,
            "rpm_ema": 2000.0,
            "Coolant_Temp": 87.0,
            "temp_ema": 87.0,
            "temp_max_10s": 88.0,
            "MAF": 35.0,  # Massive MAF surge / sensor fault
            "maf_ema": 35.0,
            "air_intake_ratio": 0.0175,  # Far above normal 0.005
            "dtemp_dt": 0.0,
            "rpm_std_10s": 20.0,
            "maf_std_10s": 9.5,
        }

        health_report = self.health_engine.evaluate_health(
            features=maf_leak_features,
            anomaly_score=0.90,
            anomaly_flag=-1
        )

        self.assertLess(health_report["air_intake_health"], 60.0)
        dtc_codes = [d["code"] for d in health_report["active_dtcs"]]
        self.assertIn("P0101", dtc_codes)


class TestEndToEndIntelligenceIntegration(unittest.TestCase):
    """Full integration test: Physics Simulator -> Logger -> Pipeline -> Anomaly Model -> Health & DTCs."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "integration_telemetry.db")
        self.model_path = os.path.join(self.temp_dir.name, "integration_model.pkl")
        self.logger = TelemetryLogger(db_path=self.db_path)
        self.pipeline = TelemetryDataPipeline(db_path=self.db_path)
        self.health_engine = SubsystemHealthEngine()

        # Train baseline model on normal driving
        self.detector = TelemetryAnomalyDetector.train_baseline_model(
            save_path=self.model_path, duration_seconds=60.0
        )

    def tearDown(self):
        if hasattr(self, "logger") and self.logger:
            self.logger.close()
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_overheat_simulation_end_to_end(self):
        """Simulates an engine overheat anomaly, ingests it, and verifies pipeline detection."""
        sim = VehiclePhysicsSimulator(inject_anomaly=True, anomaly_type="overheat")

        # Ingest 15 seconds of overheating data (150 steps @ 10 Hz)
        records = []
        t = 0.0
        for _ in range(150):
            state = sim.update()
            records.append({"timestamp": t + 0.00, "pid": "010C", "metric_name": "RPM", "decoded_value": state["rpm"], "unit": "RPM"})
            records.append({"timestamp": t + 0.02, "pid": "0105", "metric_name": "Coolant_Temp", "decoded_value": state["coolant_temp"], "unit": "°C"})
            records.append({"timestamp": t + 0.04, "pid": "0110", "metric_name": "MAF", "decoded_value": state["maf"], "unit": "g/s"})
            records.append({"timestamp": t + 0.06, "pid": "012F", "metric_name": "Fuel_Level", "decoded_value": state["fuel_level"], "unit": "%"})
            t += 0.1

        self.logger.log_batch(records)

        # Run pipeline
        feature_df = self.pipeline.process_pipeline()
        self.assertGreater(len(feature_df), 100)

        # Get latest feature window
        latest_row = feature_df.iloc[-1].to_dict()
        self.assertGreater(latest_row["Coolant_Temp"], 115.0)

        # Evaluate ML anomaly
        eval_res = self.detector.evaluate_sample(latest_row)

        # Evaluate Subsystem Health & DTCs
        health_report = self.health_engine.evaluate_health(
            features=latest_row,
            anomaly_score=eval_res["anomaly_score"],
            anomaly_flag=eval_res["anomaly_flag"]
        )

        # Assertions
        self.assertLess(health_report["thermal_health"], 60.0)
        self.assertTrue(health_report["is_anomaly"])
        dtc_codes = [d["code"] for d in health_report["active_dtcs"]]
        self.assertIn("P0117", dtc_codes)
        self.assertEqual(health_report["status"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
