"""
CarDigno - ELM327 OBD-II Mock Stream Generator
Streams realistic SAE J1979 OBD-II hexadecimal frames over an asynchronous TCP socket at 10 Hz.
"""

import asyncio
import argparse
import logging
import math
import os
import random
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ELM327-MOCK] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ELM327Mock")


class VehiclePhysicsSimulator:
    """Simulates realistic engine dynamics, thermal physics, air intake, and fuel consumption."""

    def __init__(self, inject_anomaly: bool = False, anomaly_type: str = "overheat"):
        self.inject_anomaly = inject_anomaly
        self.anomaly_type = anomaly_type
        
        # State variables
        self.t = 0.0
        self.dt = 0.1  # 10 Hz update rate (100 ms)
        
        # Driving dynamics
        self.current_state = "IDLE"  # IDLE, ACCEL, CRUISE, DECEL
        self.state_timer = 0.0
        self.target_rpm = 800.0
        self.current_rpm = 800.0
        
        # Thermal dynamics (°C)
        self.coolant_temp = 108.0 if self.inject_anomaly else 85.0
        self.fan_active = False
        
        # Air intake (g/s)
        self.current_maf = 3.2
        
        # Fuel (%)
        self.fuel_level = 88.5
        
        # Anomaly counters & multipliers
        self.anomaly_severity = 1.0

    def update(self) -> Dict[str, float]:
        """Advance physical simulation step by dt (0.1s) and return telemetry snapshot."""
        self.t += self.dt
        self.state_timer += self.dt
        
        # State machine for realistic driving cycles
        if self.current_state == "IDLE":
            if self.state_timer > random.uniform(4.0, 7.0):
                self.current_state = "ACCEL"
                self.state_timer = 0.0
                self.target_rpm = random.uniform(2600.0, 4200.0)
            else:
                self.target_rpm = 800.0 + random.gauss(0, 15.0)
                
        elif self.current_state == "ACCEL":
            if self.current_rpm >= (self.target_rpm - 100.0) or self.state_timer > 6.0:
                self.current_state = "CRUISE"
                self.state_timer = 0.0
                self.target_rpm = random.uniform(2000.0, 2600.0)
                
        elif self.current_state == "CRUISE":
            if self.state_timer > random.uniform(6.0, 12.0):
                self.current_state = "DECEL"
                self.state_timer = 0.0
                self.target_rpm = 800.0
            else:
                self.target_rpm = 2200.0 + math.sin(self.t * 0.8) * 150.0
                
        elif self.current_state == "DECEL":
            if self.current_rpm <= 850.0 or self.state_timer > 5.0:
                self.current_state = "IDLE"
                self.state_timer = 0.0
                self.target_rpm = 800.0

        # RPM smoothing
        rpm_alpha = 0.15 if self.current_state == "ACCEL" else 0.08
        self.current_rpm += (self.target_rpm - self.current_rpm) * rpm_alpha
        self.current_rpm = max(650.0, min(6500.0, self.current_rpm))
        
        # MAF physics (correlated with RPM + engine displacement factor + throttle response)
        # Normal baseline: MAF ~ (RPM * 2.0L * VE * air_density) / 120
        # 800 RPM -> ~3.0 g/s; 3000 RPM -> ~25-35 g/s; 5000 RPM -> ~60 g/s
        base_maf = (self.current_rpm / 800.0) * 3.1 + (self.current_rpm ** 1.15) * 0.003
        jitter = random.gauss(0, 0.15)
        self.current_maf = max(1.5, base_maf + jitter)
        
        # Thermal physics
        # Heat generation is proportional to RPM and MAF load
        heat_input = (self.current_rpm / 1000.0) * 0.06 + (self.current_maf / 10.0) * 0.04
        
        if self.inject_anomaly and (self.anomaly_type == "overheat" or self.anomaly_type == "all"):
            # Anomaly: Thermostat failure / radiator blockage -> No active cooling
            self.coolant_temp += 0.18 + (heat_input * 0.5)
            # Push past 115°C up to 125°C
            self.coolant_temp = min(128.0, self.coolant_temp)
        else:
            # Normal thermal equilibrium: thermostat opens at 88°C, fan engages at 94°C
            heat_dissipation = 0.03 + (0.12 if self.fan_active else 0.05) * ((self.coolant_temp - 25.0) / 70.0)
            if self.coolant_temp >= 94.0:
                self.fan_active = True
            elif self.coolant_temp <= 88.0:
                self.fan_active = False
                
            self.coolant_temp += (heat_input - heat_dissipation) * 0.25
            self.coolant_temp = max(70.0, min(97.0, self.coolant_temp))
            
        # Sensor anomalies (MAF leak or RPM misfire)
        if self.inject_anomaly and (self.anomaly_type == "maf_surge" or self.anomaly_type == "all"):
            # Erratic vacuum surge
            self.current_maf *= (1.8 + 0.5 * math.sin(self.t * 3.0))

        if self.inject_anomaly and (self.anomaly_type == "misfire" or self.anomaly_type == "all"):
            if random.random() < 0.15:
                self.current_rpm *= 0.65

        # Fuel consumption (proportional to MAF: 14.7 AFR)
        # Fuel used per sec = (MAF / 14.7) / (745 g/L)
        fuel_consumed_rate = (self.current_maf / 14.7) / 745.0  # L/s
        tank_capacity_l = 55.0  # 55 Liters
        self.fuel_level -= (fuel_consumed_rate / tank_capacity_l) * 100.0 * self.dt
        self.fuel_level = max(0.0, min(100.0, self.fuel_level))
        
        # Sensor jitter for fuel sensor float
        slosh_jitter = math.sin(self.t * 0.5) * 0.12
        displayed_fuel = max(0.0, min(100.0, self.fuel_level + slosh_jitter))

        return {
            "rpm": self.current_rpm,
            "coolant_temp": self.coolant_temp,
            "maf": self.current_maf,
            "fuel_level": displayed_fuel,
            "state": self.current_state
        }


class OBD2HexEncoder:
    """Encodes physical sensor values into SAE J1979 compliant hexadecimal responses."""

    @staticmethod
    def encode_rpm(rpm: float) -> Tuple[str, bytes]:
        """
        PID 010C: Engine RPM
        Formula: RPM = ((A * 256) + B) / 4
        Bytes: 2
        """
        raw = int(round(rpm * 4.0))
        raw = max(0, min(65535, raw))
        a = (raw >> 8) & 0xFF
        b = raw & 0xFF
        hex_str = f"41 0C {a:02X} {b:02X}\r\n"
        return hex_str, hex_str.encode("ascii")

    @staticmethod
    def encode_coolant_temp(temp_c: float) -> Tuple[str, bytes]:
        """
        PID 0105: Engine Coolant Temperature
        Formula: Temp = A - 40 (°C)
        Bytes: 1
        """
        raw = int(round(temp_c + 40.0))
        raw = max(0, min(255, raw))
        hex_str = f"41 05 {raw:02X}\r\n"
        return hex_str, hex_str.encode("ascii")

    @staticmethod
    def encode_maf(maf: float) -> Tuple[str, bytes]:
        """
        PID 0110: MAF Air Flow Rate
        Formula: MAF = ((A * 256) + B) / 100 (g/s)
        Bytes: 2
        """
        raw = int(round(maf * 100.0))
        raw = max(0, min(65535, raw))
        a = (raw >> 8) & 0xFF
        b = raw & 0xFF
        hex_str = f"41 10 {a:02X} {b:02X}\r\n"
        return hex_str, hex_str.encode("ascii")

    @staticmethod
    def encode_fuel_level(fuel_pct: float) -> Tuple[str, bytes]:
        """
        PID 012F: Fuel Tank Level Input
        Formula: Fuel = (A * 100) / 255 (%)
        Bytes: 1
        """
        raw = int(round((fuel_pct * 255.0) / 100.0))
        raw = max(0, min(255, raw))
        hex_str = f"41 2F {raw:02X}\r\n"
        return hex_str, hex_str.encode("ascii")


class ELM327Server:
    """Asynchronous TCP server broadcasting SAE J1979 OBD-II hex frames."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, rate_hz: Optional[float] = None,
                 inject_anomaly: bool = False, anomaly_type: str = "overheat"):
        self.host = host or os.getenv("CARDIGNO_SIM_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("CARDIGNO_SIM_PORT", "8000"))
        self.rate_hz = rate_hz or float(os.getenv("CARDIGNO_SIM_RATE_HZ", "10.0"))
        self.interval = 1.0 / rate_hz
        self.physics = VehiclePhysicsSimulator(inject_anomaly=inject_anomaly, anomaly_type=anomaly_type)
        self.clients: Set[asyncio.StreamWriter] = set()
        self.server: asyncio.Server = None
        self.is_running = False
        self.frame_count = 0

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Manages incoming TCP client connections and optional interactive AT/OBD-II commands."""
        peer = writer.get_extra_info("peername")
        logger.info(f"Client connected from {peer}")
        self.clients.add(writer)

        try:
            while self.is_running and not writer.is_closing():
                try:
                    # Read incoming client commands without blocking broadcast
                    line = await asyncio.wait_for(reader.readline(), timeout=0.5)
                    if not line:
                        break
                    
                    cmd = line.decode("ascii", errors="ignore").strip().upper()
                    if cmd:
                        logger.info(f"Received command from {peer}: {cmd}")
                        await self._handle_client_command(writer, cmd)
                except asyncio.TimeoutError:
                    # Non-blocking wait: continue serving broadcast
                    continue
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            logger.debug(f"Client reader notice: {e}")
        finally:
            logger.info(f"Client disconnected: {peer}")
            self.clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_client_command(self, writer: asyncio.StreamWriter, cmd: str):
        """Processes ELM327 AT commands and runtime anomaly injection controls."""
        resp = ""
        if cmd in ("ATZ", "AT Z", "AT WS"):
            resp = "ELM327 v1.5\r\n\r\n>"
        elif cmd in ("ATI", "AT I"):
            resp = "CarDigno ELM327 v1.5 OBD-II Mock\r\n>"
        elif cmd.startswith("AT"):
            resp = "OK\r\n>"
        elif cmd == "010C":
            hex_str, _ = OBD2HexEncoder.encode_rpm(self.physics.current_rpm)
            resp = f"{hex_str}>"
        elif cmd == "0105":
            hex_str, _ = OBD2HexEncoder.encode_coolant_temp(self.physics.coolant_temp)
            resp = f"{hex_str}>"
        elif cmd == "0110":
            hex_str, _ = OBD2HexEncoder.encode_maf(self.physics.current_maf)
            resp = f"{hex_str}>"
        elif cmd == "012F":
            hex_str, _ = OBD2HexEncoder.encode_fuel_level(self.physics.fuel_level)
            resp = f"{hex_str}>"
        elif cmd in ("ANOMALY ON", "SET ANOMALY ON"):
            self.physics.inject_anomaly = True
            resp = "OK: Anomaly Injection ENABLED (>115C Overheat active)\r\n>"
            logger.warning("Dynamic Anomaly Injection ENABLED via socket command")
        elif cmd in ("ANOMALY OFF", "SET ANOMALY OFF"):
            self.physics.inject_anomaly = False
            self.physics.coolant_temp = 90.0
            resp = "OK: Anomaly Injection DISABLED (Coolant reset to 90C)\r\n>"
            logger.info("Dynamic Anomaly Injection DISABLED via socket command")
        elif cmd.startswith("SET TEMP "):
            try:
                val = float(cmd.split(" ")[2])
                self.physics.coolant_temp = val
                resp = f"OK: Coolant Temp set to {val} C\r\n>"
            except Exception:
                resp = "?\r\n>"
        else:
            resp = "?\r\n>"

        if resp:
            try:
                writer.write(resp.encode("ascii"))
                await writer.drain()
            except Exception:
                pass

    async def broadcast_loop(self):
        """Continuous high-frequency broadcast loop streaming OBD-II frames at configured rate."""
        logger.info(f"Broadcasting telemetry stream at {self.rate_hz} Hz ({self.interval * 1000:.1f} ms tick)")
        
        while self.is_running:
            tick_start = time.perf_counter()
            
            # Step physics simulation
            data = self.physics.update()
            self.frame_count += 1
            
            # Encode frames for all standard PIDs
            f_rpm_str, f_rpm_bytes = OBD2HexEncoder.encode_rpm(data["rpm"])
            f_temp_str, f_temp_bytes = OBD2HexEncoder.encode_coolant_temp(data["coolant_temp"])
            f_maf_str, f_maf_bytes = OBD2HexEncoder.encode_maf(data["maf"])
            f_fuel_str, f_fuel_bytes = OBD2HexEncoder.encode_fuel_level(data["fuel_level"])
            
            # Combine package payload for this 10 Hz tick
            packet = f_rpm_bytes + f_temp_bytes + f_maf_bytes + f_fuel_bytes
            
            # Broadcast to all connected clients
            dead_clients = []
            for writer in list(self.clients):
                try:
                    writer.write(packet)
                    await writer.drain()
                except Exception:
                    dead_clients.append(writer)
                    
            for dc in dead_clients:
                self.clients.discard(dc)
                
            # Log telemetry periodically to console
            if self.frame_count % int(self.rate_hz * 2) == 0:  # Every 2 seconds
                anomaly_tag = "[ANOMALY ACTIVE]" if self.physics.inject_anomaly else "[NORMAL]"
                logger.info(
                    f"{anomaly_tag} State: {data['state']:<6} | "
                    f"RPM: {data['rpm']:6.1f} | "
                    f"Coolant: {data['coolant_temp']:5.1f}°C | "
                    f"MAF: {data['maf']:5.2f} g/s | "
                    f"Fuel: {data['fuel_level']:5.1f}% | "
                    f"Clients: {len(self.clients)}"
                )
                
            # Exact timing compensation
            elapsed = time.perf_counter() - tick_start
            sleep_duration = max(0.0, self.interval - elapsed)
            await asyncio.sleep(sleep_duration)

    async def start(self):
        """Starts the asynchronous TCP server and broadcast worker."""
        self.is_running = True
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = self.server.sockets[0].getsockname()
        logger.info(f"============================================================")
        logger.info(f" ELM327 OBD-II Mock Socket Server LIVE on {addr[0]}:{addr[1]}")
        logger.info(f" Mode: {'ANOMALY INJECTION (>115°C Overheat)' if self.physics.inject_anomaly else 'NORMAL'}")
        logger.info(f" Protocol: SAE J1979 OBD-II Hex Streaming (010C, 0105, 0110, 012F)")
        logger.info(f"============================================================")
        
        async with self.server:
            await asyncio.gather(
                self.server.serve_forever(),
                self.broadcast_loop()
            )

    def stop(self):
        """Stops the server gracefully."""
        self.is_running = False
        if self.server:
            self.server.close()


def main():
    parser = argparse.ArgumentParser(description="CarDigno ELM327 OBD-II TCP Socket Stream Generator")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="TCP Host bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="TCP Port (default: 8000)")
    parser.add_argument("--rate", type=float, default=10.0, help="Streaming rate in Hz (default: 10.0)")
    parser.add_argument("--inject-anomaly", action="store_true", help="Inject overheating (>115°C) and sensor anomalies")
    parser.add_argument("--anomaly-type", type=str, default="overheat", choices=["overheat", "maf_surge", "misfire", "all"],
                        help="Type of anomaly to simulate (default: overheat)")
    
    args = parser.parse_args()
    
    server = ELM327Server(
        host=args.host,
        port=args.port,
        rate_hz=args.rate,
        inject_anomaly=args.inject_anomaly,
        anomaly_type=args.anomaly_type
    )
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("ELM327 Mock Server stopped by user.")
    except Exception as e:
        logger.error(f"Fatal server error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
