"""
CarDigno - Phase 4 API & WebSockets Gateway Unit and Integration Tests
Verifies FastAPI REST endpoints (/api/v1/health, /api/v1/history) and WebSockets gateway (/ws/telemetry).
"""

import asyncio
import os
import tempfile
import time
import unittest
from typing import Dict, Any

from fastapi.testclient import TestClient

from backend.app import app, get_db_logger, update_latest_health_report, get_latest_health_report
from backend.websocket import manager
from telemetry_core.db_logger import TelemetryLogger


class TestFastAPIRestAPI(unittest.TestCase):
    """Unit and Integration tests for FastAPI HTTP REST Endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

        # Initialize temporary database for test queries
        cls.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = os.path.join(cls.temp_dir.name, "test_api_telemetry.db")
        cls.db_logger = TelemetryLogger(db_path=cls.db_path)

        # Override dependency to point to temporary test database
        app.dependency_overrides[get_db_logger] = lambda: cls.db_logger

        # Insert dummy telemetry records for testing /history pagination
        test_records = [
            {"timestamp": 1000.0 + i, "pid": "010C" if i % 2 == 0 else "0105",
             "metric_name": "RPM" if i % 2 == 0 else "Coolant_Temp",
             "decoded_value": 800.0 + i, "unit": "RPM" if i % 2 == 0 else "°C",
             "raw_hex": f"41 0C 00 {i:02X}"}
            for i in range(25)
        ]
        cls.db_logger.log_batch(test_records)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        if hasattr(cls, "db_logger") and cls.db_logger:
            cls.db_logger.close()
        cls.temp_dir.cleanup()

    def test_root_endpoint(self):
        """Tests root API metadata response."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data["name"], "CarDigno Vehicle Intelligence Gateway")
        self.assertEqual(json_data["status"], "ONLINE")
        self.assertIn("health", json_data["endpoints"])

    def test_health_endpoint_default(self):
        """Tests GET /api/v1/health default baseline structure."""
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("status", data)
        self.assertIn("overall_health", data)
        self.assertIn("thermal_health", data)
        self.assertIn("air_intake_health", data)
        self.assertIn("is_anomaly", data)
        self.assertIn("anomaly_score", data)
        self.assertIn("active_dtcs", data)

    def test_health_endpoint_update(self):
        """Tests GET /api/v1/health after orchestrator health state update."""
        mock_report = {
            "timestamp": time.time(),
            "overall_health": 45.0,
            "thermal_health": 40.0,
            "air_intake_health": 50.0,
            "is_anomaly": True,
            "anomaly_score": 0.85,
            "anomaly_flag": -1,
            "active_dtcs": [
                {
                    "code": "P0117",
                    "subsystem": "Thermal",
                    "severity": "CRITICAL",
                    "description": "Severe Overheating (>115°C)",
                    "recommended_action": "Safely pull over immediately."
                }
            ],
            "status": "CRITICAL",
        }
        update_latest_health_report(mock_report)

        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["status"], "CRITICAL")
        self.assertEqual(data["overall_health"], 45.0)
        self.assertEqual(len(data["active_dtcs"]), 1)
        self.assertEqual(data["active_dtcs"][0]["code"], "P0117")

    def test_history_endpoint_pagination(self):
        """Tests GET /api/v1/history pagination and default parameters using test DB."""
        response = self.client.get("/api/v1/history?page=1&limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(data["total_records"], 25)
        self.assertEqual(data["total_pages"], 3)
        self.assertEqual(len(data["data"]), 10)

    def test_history_endpoint_filtering(self):
        """Tests GET /api/v1/history with PID filter."""
        response = self.client.get("/api/v1/history?page=1&limit=20&pid=010C")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total_records"], 13)
        for item in data["data"]:
            self.assertEqual(item["pid"], "010C")


class TestWebSocketGateway(unittest.TestCase):
    """Unit and Integration tests for Real-Time WebSocket Endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_websocket_connection_and_ping(self):
        """Tests WebSocket connection and ping-pong communication."""
        with self.client.websocket_connect("/ws/telemetry") as websocket:
            websocket.send_text("ping")
            data = websocket.receive_json()
            self.assertEqual(data, {"type": "pong"})

    def test_websocket_broadcast_delivery(self):
        """Tests broadcasting telemetry payload to active WebSocket clients."""
        with self.client.websocket_connect("/ws/telemetry") as websocket:
            sample_payload = {
                "type": "telemetry_update",
                "telemetry": {
                    "timestamp": time.time(),
                    "pid": "010C",
                    "metric_name": "RPM",
                    "decoded_value": 2450.0,
                    "unit": "RPM",
                },
                "health": {
                    "overall_health": 98.5,
                    "status": "HEALTHY",
                }
            }

            # Broadcast message via ConnectionManager
            asyncio.run(manager.broadcast(sample_payload))

            received = websocket.receive_json()
            self.assertEqual(received["type"], "telemetry_update")
            self.assertEqual(received["telemetry"]["metric_name"], "RPM")
            self.assertEqual(received["telemetry"]["decoded_value"], 2450.0)


class TestAsyncOrchestrator(unittest.TestCase):
    """Tests startup and background orchestrator task lifecycle."""

    def test_orchestrator_imports_and_app_lifecycle(self):
        """Verifies backend main entrypoint module loads cleanly."""
        from backend.main import app as main_app
        self.assertIsNotNone(main_app)


if __name__ == "__main__":
    unittest.main()
