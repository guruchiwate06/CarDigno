"""
CarDigno - Live End-to-End Real-Time Telemetry & Intelligence Monitor
Demonstrates Phase 1 (Simulator), Phase 2 (Ingestion), and Phase 3 (ML Anomaly & Health Engine)
in a live, colorized terminal dashboard.
"""

import asyncio
import argparse
import os
import sys
import time
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulator.elm327_mock import ELM327Server
from telemetry_core.decoder import OBD2Decoder
from telemetry_core.db_logger import TelemetryLogger
from intelligence_engine.data_pipeline import OnlineFeaturePipeline
from intelligence_engine.anomaly_detector import TelemetryAnomalyDetector
from intelligence_engine.health_scoring import SubsystemHealthEngine

# Terminal ANSI color codes for rich dashboard rendering
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
CLEAR_SCREEN = "\033[2J\033[H"


def make_bar(pct: float, length: int = 20) -> str:
    """Generates an ANSI colorized progress bar for health ratings."""
    pct = max(0.0, min(100.0, pct))
    filled = int((pct / 100.0) * length)
    empty = length - filled
    
    if pct >= 80:
        color = GREEN
    elif pct >= 60:
        color = YELLOW
    else:
        color = RED

    bar_str = f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"
    return f"[{bar_str}] {color}{pct:5.1f}%{RESET}"


def make_anomaly_bar(score: float, length: int = 20) -> str:
    """Generates an anomaly score bar where high values are red."""
    score = max(0.0, min(1.0, score))
    filled = int(score * length)
    empty = length - filled

    if score < 0.4:
        color = GREEN
    elif score < 0.6:
        color = YELLOW
    else:
        color = RED

    bar_str = f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"
    return f"[{bar_str}] {color}{score:0.3f}{RESET}"


class LiveDashboardMonitor:
    """Orchestrates mock streaming, ingestion, ML scoring, and HUD rendering."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        inject_anomaly: bool = False,
        anomaly_type: str = "overheat",
    ):
        self.host = host
        self.port = port
        self.inject_anomaly = inject_anomaly
        self.anomaly_type = anomaly_type

        # Initialize pipeline components
        self.server = ELM327Server(
            host=self.host,
            port=self.port,
            rate_hz=10.0,
            inject_anomaly=inject_anomaly,
            anomaly_type=anomaly_type
        )
        self.decoder = OBD2Decoder()
        self.db_logger = TelemetryLogger()
        self.online_pipeline = OnlineFeaturePipeline(buffer_size=100)
        self.anomaly_detector = TelemetryAnomalyDetector()
        
        # Train baseline if not fitted
        if not self.anomaly_detector.is_fitted:
            print(f"{YELLOW}No pre-trained model found. Training baseline model...{RESET}")
            self.anomaly_detector = TelemetryAnomalyDetector.train_baseline_model(duration_seconds=30.0)

        self.health_engine = SubsystemHealthEngine()
        self.frame_count = 0
        self.start_time = time.time()
        self.last_hud_render = 0.0

    async def run(self):
        """Runs the mock server in background and connects client monitor."""
        # 1. Start Mock Server task
        server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.3)  # Allow socket to bind

        # 2. Connect client receiver
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except Exception as e:
            print(f"{RED}Failed to connect to ELM327 server at {self.host}:{self.port}: {e}{RESET}")
            self.server.stop()
            return

        print(f"{GREEN}Connected to ELM327 Mock stream. Starting live dashboard...{RESET}")
        await asyncio.sleep(0.5)

        try:
            buffer = ""
            while True:
                data = await reader.read(256)
                if not data:
                    break

                buffer += data.decode("ascii", errors="ignore")
                while "\r" in buffer:
                    line, buffer = buffer.split("\r", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # Decode SAE J1979 frame
                    decoded = self.decoder.decode_line(line, timestamp=time.time())
                    if decoded:
                        self.frame_count += 1
                        # Update online features
                        features = self.online_pipeline.update_single_metric(
                            timestamp=decoded["timestamp"],
                            metric_name=decoded["metric_name"],
                            value=decoded["decoded_value"]
                        )
                        
                        # Render HUD every 0.15s
                        now = time.time()
                        if features and (now - self.last_hud_render >= 0.15):
                            self.last_hud_render = now
                            self.render_hud(features, decoded)

        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.server.stop()
            server_task.cancel()

    def render_hud(self, features: Dict[str, float], latest_decoded: Dict[str, Any]):
        """Renders an ASCII HUD in the console."""
        # Run ML Anomaly Detection
        ml_eval = self.anomaly_detector.evaluate_sample(features)
        
        # Run Subsystem Health Scoring & DTC Engine
        health_report = self.health_engine.evaluate_health(
            features=features,
            anomaly_score=ml_eval["anomaly_score"],
            anomaly_flag=ml_eval["anomaly_flag"]
        )

        uptime = time.time() - self.start_time
        status_color = GREEN if health_report["status"] == "HEALTHY" else (YELLOW if health_report["status"] == "WARNING" else RED)

        # Build output buffer
        out = []
        out.append(CLEAR_SCREEN)
        out.append(f"{CYAN}{BOLD}╔════════════════════════════════════════════════════════════════════════════════════╗{RESET}")
        out.append(f"{CYAN}{BOLD}║                     CARDIGNO LIVE VEHICLE INTELLIGENCE HUD                         ║{RESET}")
        out.append(f"{CYAN}{BOLD}╚════════════════════════════════════════════════════════════════════════════════════╝{RESET}")
        out.append(f"  {BOLD}Uptime:{RESET} {uptime:5.1f}s | {BOLD}Frames Processed:{RESET} {self.frame_count} | {BOLD}Mode:{RESET} {RED if self.inject_anomaly else GREEN}{'ANOMALY INJECTION (' + self.anomaly_type.upper() + ')' if self.inject_anomaly else 'NORMAL DRIVING'}{RESET}")
        out.append(f"  {BOLD}Overall System Status:{RESET} {status_color}{BOLD}{health_report['status']}{RESET}\n")

        # 1. Physical Metrics Section
        out.append(f"{YELLOW}{BOLD}─── 1. LIVE SENSOR TELEMETRY (SAE J1979) ──────────────────────────────────────────{RESET}")
        out.append(f"  Engine RPM:       {BOLD}{features['RPM']:6.1f} RPM{RESET}  (EMA: {features['rpm_ema']:6.1f})")
        
        temp_val = features['Coolant_Temp']
        temp_color = RED if temp_val >= 115 else (YELLOW if temp_val >= 100 else GREEN)
        out.append(f"  Coolant Temp:     {temp_color}{BOLD}{temp_val:5.1f} °C{RESET}    (EMA: {features['temp_ema']:5.1f} °C | Max 10s: {features['temp_max_10s']:5.1f} °C)")
        out.append(f"  Mass Air Flow:    {BOLD}{features['MAF']:6.2f} g/s{RESET}  (EMA: {features['maf_ema']:6.2f} g/s)")
        out.append(f"  Fuel Tank Level:  {BOLD}{features['Fuel_Level']:5.1f} %{RESET}\n")

        # 2. Physics & Feature Engineering
        out.append(f"{MAGENTA}{BOLD}─── 2. ROLLING FEATURE VECTORS (10-SECOND WINDOW) ────────────────────────────────{RESET}")
        out.append(f"  Air Intake Ratio (MAF/RPM): {features['air_intake_ratio']:0.5f}  (Normal: ~0.0035 - 0.0080)")
        dtemp_color = RED if abs(features['dtemp_dt']) > 1.0 else (YELLOW if abs(features['dtemp_dt']) > 0.4 else WHITE)
        out.append(f"  Thermal Derivative (dTemp/dt): {dtemp_color}{features['dtemp_dt']:+0.3f} °C/s{RESET}")
        out.append(f"  RPM Instability (Std Dev 10s): {features['rpm_std_10s']:5.1f} RPM\n")

        # 3. Machine Learning Anomaly Detection
        out.append(f"{BLUE}{BOLD}─── 3. MACHINE LEARNING ANOMALY ENGINE (ISOLATION FOREST) ────────────────────────{RESET}")
        anom_flag_str = f"{RED}{BOLD}ANOMALOUS (-1){RESET}" if ml_eval["is_anomaly"] else f"{GREEN}NORMAL (+1){RESET}"
        out.append(f"  Isolation Forest State: {anom_flag_str}  |  Decision Score: {ml_eval['decision_score']:+0.4f}")
        out.append(f"  Normalized Anomaly Score: {make_anomaly_bar(ml_eval['anomaly_score'])}\n")

        # 4. Subsystem Health Degradation Ratings
        out.append(f"{GREEN}{BOLD}─── 4. SUBSYSTEM HEALTH DEGRADATION SCORES ───────────────────────────────────────{RESET}")
        out.append(f"  Thermal Subsystem Health:    {make_bar(health_report['thermal_health'])}")
        out.append(f"  Air Intake Subsystem Health: {make_bar(health_report['air_intake_health'])}")
        out.append(f"  Overall Vehicular Health:    {make_bar(health_report['overall_health'])}\n")

        # 5. Diagnostic Trouble Codes (DTCs)
        out.append(f"{RED}{BOLD}─── 5. ACTIVE DIAGNOSTIC TROUBLE CODES (DTCs) ───────────────────────────────────{RESET}")
        active_dtcs = health_report["active_dtcs"]
        if not active_dtcs:
            out.append(f"  {GREEN}✔ No Active Trouble Codes. All subsystems nominal.{RESET}")
        else:
            for dtc in active_dtcs:
                sev_color = RED if dtc["severity"] == "CRITICAL" else YELLOW
                out.append(f"  {sev_color}{BOLD}▶ [{dtc['code']}]{RESET} {BOLD}{dtc['description']}{RESET}")
                out.append(f"    {DIM}Severity: {dtc['severity']} | Action: {dtc['recommended_action']}{RESET}")

        out.append(f"\n{DIM}Press Ctrl+C to stop monitor.{RESET}")
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="CarDigno Live Telemetry & Intelligence HUD")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--inject-anomaly", action="store_true", help="Inject vehicle anomalies")
    parser.add_argument(
        "--anomaly-type",
        type=str,
        default="overheat",
        choices=["overheat", "maf_surge", "misfire", "all"],
        help="Anomaly type to simulate (default: overheat)",
    )

    args = parser.parse_args()

    monitor = LiveDashboardMonitor(
        host=args.host,
        port=args.port,
        inject_anomaly=args.inject_anomaly,
        anomaly_type=args.anomaly_type,
    )

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Live Monitor stopped by user.{RESET}")


if __name__ == "__main__":
    main()
