"""
Unit and integration tests for CarDigno Telemetry Ingestion Core (Decoder, SQLite WAL Logger, Receiver).
"""

import asyncio
import os
import sqlite3
import tempfile
import time
import unittest

from telemetry_core.decoder import OBD2Decoder
from telemetry_core.db_logger import TelemetryLogger
from telemetry_core.receiver import TelemetryReceiver
from simulator.elm327_mock import ELM327Server


class TestOBD2Decoder(unittest.TestCase):
    """Unit tests for SAE J1979 OBD-II frame decoding logic."""

    def test_decode_rpm(self):
        # 41 0C 1F 40 -> ((31 * 256) + 64) / 4 = 8000 / 4 = 2000.0 RPM
        line = "41 0C 1F 40\r\n"
        res = OBD2Decoder.decode_line(line)
        self.assertIsNotNone(res)
        self.assertEqual(res["pid"], "010C")
        self.assertEqual(res["metric_name"], "RPM")
        self.assertEqual(res["decoded_value"], 2000.0)
        self.assertEqual(res["unit"], "RPM")

    def test_decode_coolant_temp(self):
        # 41 05 80 -> 128 - 40 = 88.0 °C
        line = "41 05 80\r"
        res = OBD2Decoder.decode_line(line)
        self.assertIsNotNone(res)
        self.assertEqual(res["pid"], "0105")
        self.assertEqual(res["metric_name"], "Coolant_Temp")
        self.assertEqual(res["decoded_value"], 88.0)
        self.assertEqual(res["unit"], "°C")

    def test_decode_maf(self):
        # 41 10 05 DC -> ((5 * 256) + 220) / 100 = 1500 / 100 = 15.0 g/s
        line = "41 10 05 DC"
        res = OBD2Decoder.decode_line(line)
        self.assertIsNotNone(res)
        self.assertEqual(res["pid"], "0110")
        self.assertEqual(res["metric_name"], "MAF")
        self.assertEqual(res["decoded_value"], 15.0)
        self.assertEqual(res["unit"], "g/s")

    def test_decode_fuel_level(self):
        # 41 2F CC -> (204 * 100) / 255 = 80.0 %
        line = "41 2F CC\r\n"
        res = OBD2Decoder.decode_line(line)
        self.assertIsNotNone(res)
        self.assertEqual(res["pid"], "012F")
        self.assertEqual(res["metric_name"], "Fuel_Level")
        self.assertEqual(res["decoded_value"], 80.0)
        self.assertEqual(res["unit"], "%")

    def test_decode_stream_buffer_fragmentation(self):
        # Incomplete buffer chunks
        chunk1 = "41 0C 1F 40\r\n41 05 "
        records, remainder = OBD2Decoder.decode_stream_buffer(chunk1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["metric_name"], "RPM")
        self.assertEqual(remainder, "41 05 ")

        # Second chunk completes the previous frame
        chunk2 = remainder + "80\r\n41 10 05 DC\r\n"
        records2, remainder2 = OBD2Decoder.decode_stream_buffer(chunk2)
        self.assertEqual(len(records2), 2)
        self.assertEqual(records2[0]["metric_name"], "Coolant_Temp")
        self.assertEqual(records2[1]["metric_name"], "MAF")
        self.assertEqual(remainder2, "")


class TestTelemetryLogger(unittest.TestCase):
    """Unit tests for SQLite WAL mode logger."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_telemetry.db")
        self.logger = TelemetryLogger(db_path=self.db_path)

    def tearDown(self):
        if hasattr(self, "logger") and self.logger:
            self.logger.close()
        self.temp_dir.cleanup()

    def test_wal_mode_enabled(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        self.assertEqual(mode.lower(), "wal")

    def test_batch_insertion(self):
        records = [
            {"timestamp": time.time(), "pid": "010C", "metric_name": "RPM", "decoded_value": 850.0, "unit": "RPM", "raw_hex": "41 0C 0D 48"},
            {"timestamp": time.time(), "pid": "0105", "metric_name": "Coolant_Temp", "decoded_value": 90.0, "unit": "°C", "raw_hex": "41 05 82"},
            {"timestamp": time.time(), "pid": "0110", "metric_name": "MAF", "decoded_value": 3.45, "unit": "g/s", "raw_hex": "41 10 01 59"},
            {"timestamp": time.time(), "pid": "012F", "metric_name": "Fuel_Level", "decoded_value": 85.5, "unit": "%", "raw_hex": "41 2F DA"}
        ]
        inserted = self.logger.log_batch(records)
        self.assertEqual(inserted, 4)
        self.assertEqual(self.logger.get_count(), 4)

        # Query recent
        recent = self.logger.query_recent(limit=10)
        self.assertEqual(len(recent), 4)

        # Latest metrics snapshot
        latest = self.logger.get_latest_metrics()
        self.assertIn("010C", latest)
        self.assertEqual(latest["010C"]["decoded_value"], 850.0)


class TestIngestionIntegration(unittest.TestCase):
    """End-to-end integration test running simulator and receiver."""

    def test_end_to_end_ingestion(self):
        async def run_pipeline():
            temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            test_db = os.path.join(temp_dir.name, "integration.db")
            
            # Start local mock server on test port 8009
            server = ELM327Server(host="127.0.0.1", port=8009, rate_hz=20.0)
            server_task = asyncio.create_task(server.start())
            await asyncio.sleep(0.1)

            # Start receiver to consume 20 records
            receiver = TelemetryReceiver(
                host="127.0.0.1",
                port=8009,
                batch_size=5,
                db_path=test_db
            )
            
            await receiver.start(max_records=20)
            
            # Cleanup server
            server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

            # Verify SQLite records
            db_logger = TelemetryLogger(db_path=test_db)
            count = db_logger.get_count()
            metrics = db_logger.get_latest_metrics()
            
            db_logger.close()
            receiver.db_logger.close()
            temp_dir.cleanup()
            return count, metrics

        count, metrics = asyncio.run(run_pipeline())
        self.assertGreaterEqual(count, 20)
        self.assertIn("010C", metrics)
        self.assertIn("0105", metrics)


if __name__ == "__main__":
    unittest.main()
