# CarDigno: End-to-End Vehicle Diagnostic & Intelligence Platform

CarDigno is an enterprise-grade vehicle diagnostic and telemetry intelligence system. It ingests high-frequency SAE J1979 OBD-II telemetry, computes rolling features, runs real-time unsupervised anomaly detection with an Isolation Forest model, logs to high-throughput SQLite WAL storage, and visualizes live vehicular health and DTC alerts on an interactive web dashboard.

---

## Subsystem Architecture

```text
car-diagnostics-intelligence/
├── docs/                 # System architecture & API documentation
├── database/             # SQLite storage (WAL mode)
├── simulator/            # Mock ELM327 TCP socket stream generator
├── telemetry_core/       # Receiver, CAN hex decoder, SQLite batch logger
├── intelligence_engine/  # Feature engineering, Isolation Forest, health scoring
├── app_services/        # FastAPI REST API, WebSocket server, range calculator
└── visualization/        # HTML5, CSS3, JavaScript, SVG canvas, Chart.js
```

---

## Phase Roadmap
- [x] **Phase 1**: Simulator Subsystem & OBD-II Hex Stream Generator
- [x] **Phase 2**: Telemetry Ingestion Core & SQLite WAL Batch Logger
- [ ] **Phase 3**: Predictive Analytics & Unsupervised Anomaly Engine
- [ ] **Phase 4**: Application Services & WebSocket Telemetry Streamer
- [ ] **Phase 5**: Spatial HUD & Interactive 2D Vehicle Visualization
