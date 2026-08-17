"""
CarDigno - Async System Orchestrator
Launches Phase 2 Telemetry Ingestion Receiver and Phase 3 ML Intelligence Engine
as asynchronous background tasks on FastAPI startup.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI

from backend.app import create_app, update_latest_health_report
from backend.websocket import manager
from telemetry_core.receiver import TelemetryReceiver
from intelligence_engine.data_pipeline import OnlineFeaturePipeline
from intelligence_engine.anomaly_detector import TelemetryAnomalyDetector
from intelligence_engine.health_scoring import SubsystemHealthEngine

logger = logging.getLogger("Orchestrator")

# Orchestrator state variables
receiver_task: Optional[asyncio.Task] = None
receiver_instance: Optional[TelemetryReceiver] = None


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    FastAPI Lifespan Context Manager:
    Instantiates ML models, online feature pipeline, and launches telemetry receiver background task on startup,
    then cleans up background tasks on shutdown.
    """
    global receiver_task, receiver_instance
    logger.info("Initializing CarDigno Orchestrator background services...")

    # 1. Initialize ML Anomaly Detector
    anomaly_detector = TelemetryAnomalyDetector()
    if not anomaly_detector.is_fitted:
        logger.warning("No pre-trained ML model found. Training baseline model...")
        anomaly_detector = TelemetryAnomalyDetector.train_baseline_model(duration_seconds=10.0)

    # 2. Initialize Feature Pipeline & Health Engine
    online_pipeline = OnlineFeaturePipeline()
    health_engine = SubsystemHealthEngine()
    
    main_loop = asyncio.get_running_loop()

    # 3. Callback function triggered on each decoded telemetry frame
    def handle_telemetry_record(record: Dict[str, Any]):
        try:
            timestamp = record.get("timestamp", time.time())
            metric_name = record.get("metric_name", "")
            value = record.get("decoded_value", 0.0)

            # Update real-time rolling feature vector
            features = online_pipeline.update_single_metric(timestamp, metric_name, value)
            
            if features:
                # Evaluate ML anomaly score
                ml_eval = anomaly_detector.evaluate_sample(features)
                
                # Compute subsystem health & DTCs
                health_report = health_engine.evaluate_health(
                    features=features,
                    anomaly_score=ml_eval["anomaly_score"],
                    anomaly_flag=ml_eval["anomaly_flag"]
                )
                
                # Update global REST state
                update_latest_health_report(health_report)

                # Prepare real-time WebSocket broadcast payload
                payload = {
                    "type": "telemetry_update",
                    "telemetry": record,
                    "features": features,
                    "health": health_report
                }

                # Schedule async broadcast to all connected dashboard clients
                if main_loop and main_loop.is_running():
                    main_loop.create_task(manager.broadcast(payload))

        except Exception as err:
            logger.error(f"Error processing telemetry frame in orchestrator: {err}")

    # 4. Start Telemetry Receiver background task
    receiver_instance = TelemetryReceiver(on_record_callback=handle_telemetry_record)
    receiver_task = asyncio.create_task(receiver_instance.start())
    logger.info("Successfully launched Telemetry Receiver and ML Intelligence Engine in background.")

    yield  # Application runs here

    # 5. Shutdown cleanup
    logger.info("Shutting down CarDigno Orchestrator background services...")
    if receiver_instance:
        receiver_instance.stop()
    if receiver_task:
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass
    logger.info("CarDigno Orchestrator shutdown complete.")


# Instantiate app with orchestrator lifespan
app = create_app(lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
