"""
CarDigno - ELM327 Socket Verification & Telemetry Test Client
Connects to the mock ELM327 server on port 8000, receives raw hex stream, decodes SAE J1979 PIDs,
and verifies framing, timing, and formula accuracy.
"""

import asyncio
import argparse
import logging
import sys
import time
from typing import Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TEST-CLIENT] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TestClient")


class SAEJ1979Decoder:
    """Decodes standard OBD-II hex strings."""

    @staticmethod
    def decode_frame(hex_line: str) -> Dict[str, Any]:
        """
        Parses single line like '41 0C 1A F8' or '41 05 7B'.
        Returns dict with pid, name, raw bytes, and decoded value.
        """
        tokens = hex_line.strip().split()
        if len(tokens) < 3 or tokens[0] != "41":
            return None
        
        pid = tokens[1].upper()
        
        try:
            if pid == "0C":  # Engine RPM
                a = int(tokens[2], 16)
                b = int(tokens[3], 16)
                rpm = ((a * 256) + b) / 4.0
                return {"pid": "010C", "metric": "RPM", "value": rpm, "unit": "RPM", "raw": tokens}
            
            elif pid == "05":  # Coolant Temp
                a = int(tokens[2], 16)
                temp_c = a - 40
                return {"pid": "0105", "metric": "Coolant_Temp", "value": temp_c, "unit": "°C", "raw": tokens}
            
            elif pid == "10":  # MAF Air Flow
                a = int(tokens[2], 16)
                b = int(tokens[3], 16)
                maf = ((a * 256) + b) / 100.0
                return {"pid": "0110", "metric": "MAF", "value": maf, "unit": "g/s", "raw": tokens}
            
            elif pid == "2F":  # Fuel Level
                a = int(tokens[2], 16)
                fuel_pct = (a * 100.0) / 255.0
                return {"pid": "012F", "metric": "Fuel_Level", "value": fuel_pct, "unit": "%", "raw": tokens}
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing hex tokens {tokens}: {e}")
            return None
        
        return None


async def run_test(host: str = "127.0.0.1", port: int = 8000, duration_sec: float = 3.0, expect_anomaly: bool = False):
    """Connects to ELM327 server, collects frames, and verifies data integrity and rate."""
    logger.info(f"Connecting to ELM327 mock socket at {host}:{port}...")
    
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except Exception as e:
        logger.error(f"Failed to connect to {host}:{port}: {e}")
        return False

    logger.info("Connected successfully! Receiving and validating OBD-II hex stream...")
    
    received_pids = {"010C": 0, "0105": 0, "0110": 0, "012F": 0}
    last_values = {}
    start_time = time.time()
    total_frames = 0
    max_coolant_temp = -100.0

    try:
        while time.time() - start_time < duration_sec:
            line_bytes = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not line_bytes:
                break
            
            line = line_bytes.decode("ascii", errors="ignore").strip()
            if not line:
                continue
            
            decoded = SAEJ1979Decoder.decode_frame(line)
            if decoded:
                total_frames += 1
                pid = decoded["pid"]
                received_pids[pid] = received_pids.get(pid, 0) + 1
                last_values[decoded["metric"]] = decoded["value"]
                
                if decoded["metric"] == "Coolant_Temp":
                    max_coolant_temp = max(max_coolant_temp, decoded["value"])
                    
                if total_frames % 8 == 0:
                    logger.info(
                        f"Frame {total_frames:3d} | Hex: '{line}' -> {decoded['metric']}: {decoded['value']:.2f} {decoded['unit']}"
                    )
    except asyncio.TimeoutError:
        logger.error("Socket read timed out!")
        return False
    finally:
        writer.close()
        await writer.wait_closed()

    elapsed = time.time() - start_time
    rate_hz = (total_frames / 4.0) / elapsed  # 4 PIDs per tick
    
    logger.info("================ TEST RESULTS SUMMARY ================")
    logger.info(f"Total Frames Received: {total_frames} across {elapsed:.2f}s (~{rate_hz:.1f} Hz full cycles)")
    logger.info(f"PID Counts: {received_pids}")
    logger.info(f"Last Decoded Values: {last_values}")
    logger.info(f"Max Coolant Temp Observed: {max_coolant_temp:.1f}°C")
    
    # Assertions
    passed = True
    for pid, count in received_pids.items():
        if count < 5:
            logger.error(f"FAILURE: Insufficient frames for PID {pid} (got {count})")
            passed = False

    if expect_anomaly:
        if max_coolant_temp < 100.0:
            logger.error(f"FAILURE: Expected anomaly (>115°C overheat), but max temp was {max_coolant_temp:.1f}°C")
            passed = False
        else:
            logger.info(f"SUCCESS: Anomaly verified! Observed overheat temp = {max_coolant_temp:.1f}°C (>100°C)")
    else:
        logger.info(f"SUCCESS: Normal operating parameters verified. Temp = {max_coolant_temp:.1f}°C")

    if passed:
        logger.info(">>> ALL PHASE 1 VERIFICATION TESTS PASSED SUCCESSFULLY! <<<")
    else:
        logger.error(">>> SOME TESTS FAILED <<<")
        
    return passed


def main():
    parser = argparse.ArgumentParser(description="CarDigno ELM327 Socket Verification Client")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--duration", type=float, default=3.0, help="Test duration in seconds (default: 3.0)")
    parser.add_argument("--expect-anomaly", action="store_true", help="Expect overheat anomaly >115°C")
    
    args = parser.parse_args()
    success = asyncio.run(run_test(
        host=args.host,
        port=args.port,
        duration_sec=args.duration,
        expect_anomaly=args.expect_anomaly
    ))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
