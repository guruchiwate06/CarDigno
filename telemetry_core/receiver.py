"""
CarDigno - Telemetry Ingestion Receiver
Asynchronous TCP socket client that ingests raw OBD-II hex frames from the simulator,
decodes them using SAE J1979 formulas, and batch-logs records to SQLite WAL storage.
"""

import asyncio
import argparse
import logging
import os
import sys
import time
from typing import Callable, List, Optional, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telemetry_core.decoder import OBD2Decoder
from telemetry_core.db_logger import TelemetryLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [RECEIVER] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Receiver")


class TelemetryReceiver:
    """
    Asynchronous TCP client that connects to the ELM327 mock socket server,
    buffers incoming hex frames, decodes them, and commits them in batches to SQLite.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        batch_size: int = 10,
        db_path: Optional[str] = None,
        on_record_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.host = host
        self.port = port
        self.batch_size = batch_size
        self.db_logger = TelemetryLogger(db_path=db_path)
        self.on_record_callback = on_record_callback
        
        self.buffer: List[Dict[str, Any]] = []
        self.is_running = False
        self.total_received = 0
        self.total_inserted = 0
        self.last_flush_time = time.time()

    def flush_buffer(self) -> int:
        """Flushes the current in-memory buffer into SQLite WAL storage."""
        if not self.buffer:
            return 0
        
        count = len(self.buffer)
        to_insert = list(self.buffer)
        self.buffer.clear()
        
        inserted = self.db_logger.log_batch(to_insert)
        self.total_inserted += inserted
        self.last_flush_time = time.time()
        
        logger.debug(f"Flushed batch of {inserted} records to database. Total logged: {self.total_inserted}")
        return inserted

    async def start(self, max_records: Optional[int] = None):
        """
        Connects to TCP socket and starts continuous ingestion loop.
        Optionally stops after receiving max_records (used for testing).
        """
        self.is_running = True
        retry_delay = 1.0
        
        logger.info(f"Starting Telemetry Receiver targeting {self.host}:{self.port} (Batch size: {self.batch_size})")

        while self.is_running:
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                logger.info(f"Successfully connected to ELM327 source at {self.host}:{self.port}")
                retry_delay = 1.0  # Reset backoff on successful connection
                
                raw_text_buffer = ""

                while self.is_running:
                    # Read incoming chunks from socket
                    try:
                        chunk = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Timed flush check if buffer has uncommitted records
                        if self.buffer and (time.time() - self.last_flush_time > 0.5):
                            self.flush_buffer()
                        continue

                    if not chunk:
                        logger.warning("Socket closed by remote peer.")
                        break

                    raw_text = chunk.decode("ascii", errors="ignore")
                    raw_text_buffer += raw_text

                    # Decode all completed lines in buffer
                    decoded_records, raw_text_buffer = OBD2Decoder.decode_stream_buffer(raw_text_buffer)

                    for record in decoded_records:
                        self.total_received += 1
                        self.buffer.append(record)

                        # Trigger callback if registered (e.g. for downstream ML / WebSockets)
                        if self.on_record_callback:
                            try:
                                self.on_record_callback(record)
                            except Exception as cb_err:
                                logger.error(f"Error in record callback: {cb_err}")

                        # Check batch flush
                        if len(self.buffer) >= self.batch_size:
                            self.flush_buffer()

                        # Progress logging
                        if self.total_received % (self.batch_size * 4) == 0:
                            logger.info(
                                f"Ingestion Progress: {self.total_received} frames decoded | "
                                f"{self.total_inserted} rows committed in DB | "
                                f"Latest: {record['metric_name']} = {record['decoded_value']} {record['unit']}"
                            )

                        if max_records and self.total_received >= max_records:
                            logger.info(f"Target record limit reached ({max_records} records). Stopping.")
                            self.is_running = False
                            break

                # Flush any remaining items before reconnecting or exiting
                self.flush_buffer()
                writer.close()
                await writer.wait_closed()

            except (ConnectionRefusedError, OSError) as e:
                if self.is_running:
                    logger.warning(f"Connection failed: {e}. Retrying in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(5.0, retry_delay * 1.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in receiver loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

        # Final cleanup flush
        self.flush_buffer()
        logger.info(f"Telemetry Receiver stopped. Total inserted rows: {self.total_inserted}")

    def stop(self):
        """Signals the receiver loop to stop."""
        self.is_running = False
        self.flush_buffer()


def main():
    parser = argparse.ArgumentParser(description="CarDigno Telemetry Ingestion Receiver")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="ELM327 server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="ELM327 server port (default: 8000)")
    parser.add_argument("--batch-size", type=int, default=10, help="SQLite batch insert size (default: 10)")
    parser.add_argument("--db-path", type=str, default=None, help="Custom SQLite database path")
    parser.add_argument("--max-records", type=int, default=None, help="Stop after N records (for testing)")
    
    args = parser.parse_args()
    
    receiver = TelemetryReceiver(
        host=args.host,
        port=args.port,
        batch_size=args.batch_size,
        db_path=args.db_path
    )
    
    try:
        asyncio.run(receiver.start(max_records=args.max_records))
    except KeyboardInterrupt:
        logger.info("Receiver stopped by user.")
    except Exception as e:
        logger.error(f"Fatal receiver error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
