"""
Unit tests for CarDigno ELM327 Mock Simulator & SAE J1979 Hex Encoding/Decoding.
"""

import unittest
from simulator.elm327_mock import OBD2HexEncoder, VehiclePhysicsSimulator
from simulator.test_client import SAEJ1979Decoder


class TestOBD2Formulas(unittest.TestCase):
    """Verifies exact SAE J1979 formulas and round-trip encoding/decoding."""

    def test_rpm_encoding_decoding(self):
        test_rpms = [0.0, 750.0, 800.0, 2450.25, 4500.0, 6500.0]
        for rpm in test_rpms:
            hex_str, hex_bytes = OBD2HexEncoder.encode_rpm(rpm)
            decoded = SAEJ1979Decoder.decode_frame(hex_str)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded["pid"], "010C")
            self.assertEqual(decoded["metric"], "RPM")
            # RPM resolution is 0.25 RPM
            self.assertAlmostEqual(decoded["value"], rpm, delta=0.25)

    def test_coolant_temp_encoding_decoding(self):
        test_temps = [-40.0, 0.0, 25.0, 85.0, 92.0, 115.0, 125.0]
        for temp_c in test_temps:
            hex_str, hex_bytes = OBD2HexEncoder.encode_coolant_temp(temp_c)
            decoded = SAEJ1979Decoder.decode_frame(hex_str)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded["pid"], "0105")
            self.assertEqual(decoded["metric"], "Coolant_Temp")
            # Temp resolution is 1 °C
            self.assertAlmostEqual(decoded["value"], temp_c, delta=1.0)

    def test_maf_encoding_decoding(self):
        test_mafs = [0.0, 2.54, 15.82, 45.10, 120.0]
        for maf in test_mafs:
            hex_str, hex_bytes = OBD2HexEncoder.encode_maf(maf)
            decoded = SAEJ1979Decoder.decode_frame(hex_str)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded["pid"], "0110")
            self.assertEqual(decoded["metric"], "MAF")
            # MAF resolution is 0.01 g/s
            self.assertAlmostEqual(decoded["value"], maf, delta=0.01)

    def test_fuel_level_encoding_decoding(self):
        test_fuels = [0.0, 25.0, 50.0, 75.0, 100.0]
        for fuel in test_fuels:
            hex_str, hex_bytes = OBD2HexEncoder.encode_fuel_level(fuel)
            decoded = SAEJ1979Decoder.decode_frame(hex_str)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded["pid"], "012F")
            self.assertEqual(decoded["metric"], "Fuel_Level")
            # Fuel resolution is 100/255 ≈ 0.392%
            self.assertAlmostEqual(decoded["value"], fuel, delta=0.5)

    def test_physics_simulation_normal(self):
        sim = VehiclePhysicsSimulator(inject_anomaly=False)
        for _ in range(50):
            data = sim.update()
            self.assertGreaterEqual(data["rpm"], 650.0)
            self.assertLessEqual(data["rpm"], 6500.0)
            self.assertGreaterEqual(data["coolant_temp"], 70.0)
            self.assertLessEqual(data["coolant_temp"], 98.0)
            self.assertGreater(data["maf"], 1.0)
            self.assertGreaterEqual(data["fuel_level"], 0.0)

    def test_physics_simulation_overheat_anomaly(self):
        sim = VehiclePhysicsSimulator(inject_anomaly=True, anomaly_type="overheat")
        for _ in range(250):  # 25 seconds simulation time
            data = sim.update()
        self.assertGreater(data["coolant_temp"], 115.0)


if __name__ == "__main__":
    unittest.main()
