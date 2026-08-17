"""
CarDigno - FastAPI Gateway & REST API Architecture
Exposes HTTP REST endpoints for subsystem health ratings, Diagnostic Trouble Codes (DTCs),
and paginated historical telemetry records.
"""

import time
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

from telemetry_core.db_logger import TelemetryLogger
from backend.websocket import ws_router

logger = logging.getLogger("FastAPIGateway")

# Global health state holder (updated continuously by Orchestrator)
_LATEST_HEALTH_REPORT: Dict[str, Any] = {
    "status": "HEALTHY",
    "overall_health": 100.0,
    "thermal_health": 100.0,
    "air_intake_health": 100.0,
    "is_anomaly": False,
    "anomaly_score": 0.0,
    "anomaly_flag": 1,
    "active_dtcs": [],
    "timestamp": time.time(),
}


def update_latest_health_report(report: Dict[str, Any]):
    """Updates global in-memory health report state."""
    global _LATEST_HEALTH_REPORT
    _LATEST_HEALTH_REPORT = dict(report)


def get_latest_health_report() -> Dict[str, Any]:
    """Returns current global health report state."""
    return _LATEST_HEALTH_REPORT


def get_db_logger() -> TelemetryLogger:
    """Dependency provider for TelemetryLogger instance."""
    return TelemetryLogger()


def create_app(lifespan=None) -> FastAPI:
    """Constructs and configures the FastAPI Gateway application."""
    app = FastAPI(
        title="CarDigno Vehicle Intelligence Gateway",
        description="Real-Time OBD-II Telemetry Ingestion, ML Anomaly Detection & Diagnostic API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Enable CORS for local web dashboards and frontends
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount WebSocket router
    app.include_router(ws_router)

    @app.get("/")
    async def root():
        """Root API information endpoint."""
        return {
            "name": "CarDigno Vehicle Intelligence Gateway",
            "version": "1.0.0",
            "status": "ONLINE",
            "documentation": "/docs",
            "endpoints": {
                "health": "/api/v1/health",
                "history": "/api/v1/history",
                "websocket": "/ws/telemetry",
            },
        }

    @app.get("/api/v1/health")
    async def get_system_health():
        """
        GET /api/v1/health
        Returns current subsystem health ratings (Thermal, Air Intake, Overall)
        and active SAE J2012 Diagnostic Trouble Codes (DTCs).
        """
        report = get_latest_health_report()
        return report

    @app.get("/api/v1/history")
    async def get_telemetry_history(
        page: int = Query(1, ge=1, description="Page index (1-based)"),
        limit: int = Query(50, ge=1, le=1000, description="Records per page (max 1000)"),
        pid: Optional[str] = Query(None, description="Filter by PID hex code (e.g. 010C)"),
        metric_name: Optional[str] = Query(None, description="Filter by metric name (e.g. RPM)"),
        start_time: Optional[float] = Query(None, description="Filter records >= unix timestamp"),
        end_time: Optional[float] = Query(None, description="Filter records <= unix timestamp"),
        db_logger: TelemetryLogger = Depends(get_db_logger),
    ):
        """
        GET /api/v1/history
        Returns paginated time-series telemetry records from SQLite WAL storage.
        """
        try:
            res = db_logger.query_paginated(
                page=page,
                limit=limit,
                pid=pid,
                metric_name=metric_name,
                start_time=start_time,
                end_time=end_time,
            )
            return res
        except Exception as e:
            logger.error(f"Error querying telemetry history: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to query database: {str(e)}")

    return app


# Application instance
app = create_app()
