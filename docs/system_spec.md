# CarDigno System Specification & Architecture

## 1. Overview
CarDigno is an end-to-end vehicle diagnostic and intelligence platform designed for high-frequency telemetry ingestion, real-time machine learning anomaly detection, subsystem health degradation scoring, and interactive web-based 2D spatial visualization.

```
+---------------------+       Raw OBD-II Hex (10 Hz)       +------------------------+
|  ELM327 Mock Stream | ---------------------------------> |     Telemetry Core     |
|   (Port 8000 TCP)   |                                    | (Decoder + SQLite WAL) |
+---------------------+                                    +------------------------+
                                                                       |
                                                                       v
+---------------------+       10s Rolling Window Analysis   +------------------------+
| Visualization UI    | <---------------------------------- |  Intelligence Engine   |
| (SVG + Chart.js WS) |                                    | (IsolationForest + DTC)|
+---------------------+                                    +------------------------+
           ^                                                           |
           |                  FastAPI + WebSockets (Port 8080)         |
           +-----------------------------------------------------------+
```

## 2. OBD-II PID Mapping & Formulas (SAE J1979)

| PID | Description | Unit | Byte Count | Formula |
| :--- | :--- | :--- | :--- | :--- |
| `010C` | Engine RPM | RPM | 2 (`A`, `B`) | `((A * 256) + B) / 4` |
| `0105` | Engine Coolant Temperature | °C | 1 (`A`) | `A - 40` |
| `0110` | MAF Air Flow Rate | g/s | 2 (`A`, `B`) | `((A * 256) + B) / 100` |
| `012F` | Fuel Tank Level Input | % | 1 (`A`) | `(A * 100) / 255` |

## 3. Subsystem Breakdown

1. **`simulator/`**: Asynchronous TCP socket ELM327 transmitter emitting standard OBD-II hex frames at 10 Hz with dynamic engine physics and anomaly injection capabilities.
2. **`telemetry_core/`**: TCP client ingestion receiver, frame tokenizer, SAE J1979 hex decoder, and high-throughput SQLite WAL batch logger.
3. **`intelligence_engine/`**: 10-second rolling-window feature extractor (EMA of RPM/MAF, Air Intake Ratio, Thermal Derivative), scikit-learn Isolation Forest anomaly detector, and component health degradation calculator with DTC mapping.
4. **`app_services/`**: FastAPI REST API and full-duplex WebSocket server (`/ws/telemetry`), fuel consumption and estimated remaining range calculator.
5. **`visualization/`**: Interactive real-time web UI featuring 2D vehicle SVG schematic with dynamic component heat-mapping, live Chart.js graphs, and telemetry HUD gauges.
