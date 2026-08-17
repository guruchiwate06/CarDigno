"""
CarDigno - High-Throughput SQLite WAL Telemetry Logger
Stores structured vehicular time-series telemetry records in SQLite with WAL mode optimization.
"""

import contextlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

logger = logging.getLogger("TelemetryLogger")

try:
    from telemetry_core.config import settings
    DEFAULT_DB_PATH = settings.DB_PATH
except ImportError:
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "telemetry.db")


class TelemetryLogger:
    """
    Manages SQLite database storage for decoded OBD-II telemetry streams.
    Configured with Write-Ahead Logging (WAL) for high-frequency concurrent read/write operations.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        
        # Ensure database directory exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(db_dir, exist_ok=True)
        
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        """Yields a connection with WAL and timeout pragmas applied, closing it on exit."""
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.close()
            yield conn
        finally:
            conn.close()

    def close(self):
        """Forces WAL checkpoint and connection cleanup."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
        except Exception:
            pass

    def _init_db(self):
        """Initializes database schema and indexes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    pid TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    decoded_value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    raw_hex TEXT
                );
            """)
            
            # Optimized indexes for high-speed time-series and metric filtering
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry_logs(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_pid ON telemetry_logs(pid);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_metric ON telemetry_logs(metric_name);")
            conn.commit()
            logger.info(f"Initialized SQLite database at '{self.db_path}' (WAL mode enabled)")

    def log_batch(self, records: List[Dict[str, Any]]) -> int:
        """
        Inserts a batch of structured telemetry records in a single atomic transaction.
        Returns the count of successfully inserted records.
        """
        if not records:
            return 0
        
        rows = [
            (
                r.get("timestamp", 0.0),
                r.get("pid", "UNKNOWN"),
                r.get("metric_name", "UNKNOWN"),
                float(r.get("decoded_value", 0.0)),
                r.get("unit", ""),
                r.get("raw_hex", "")
            )
            for r in records
        ]

        sql = """
            INSERT INTO telemetry_logs (timestamp, pid, metric_name, decoded_value, unit, raw_hex)
            VALUES (?, ?, ?, ?, ?, ?);
        """
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()
            count = cursor.rowcount
            
        return count

    def get_count(self) -> int:
        """Returns the total number of telemetry records stored."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM telemetry_logs;")
            count = cursor.fetchone()[0]
            return count

    def query_recent(self, limit: int = 100, pid: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries the most recent records, optionally filtered by PID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if pid:
                cursor.execute(
                    "SELECT timestamp, pid, metric_name, decoded_value, unit, raw_hex FROM telemetry_logs "
                    "WHERE pid = ? ORDER BY id DESC LIMIT ?;",
                    (pid, limit)
                )
            else:
                cursor.execute(
                    "SELECT timestamp, pid, metric_name, decoded_value, unit, raw_hex FROM telemetry_logs "
                    "ORDER BY id DESC LIMIT ?;",
                    (limit,)
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def query_paginated(
        self,
        page: int = 1,
        limit: int = 50,
        pid: Optional[str] = None,
        metric_name: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Queries paginated telemetry logs with optional filtering."""
        page = max(1, page)
        limit = max(1, min(1000, limit))
        offset = (page - 1) * limit

        where_clauses = []
        params: List[Any] = []

        if pid:
            where_clauses.append("pid = ?")
            params.append(pid)
        if metric_name:
            where_clauses.append("metric_name = ?")
            params.append(metric_name)
        if start_time is not None:
            where_clauses.append("timestamp >= ?")
            params.append(float(start_time))
        if end_time is not None:
            where_clauses.append("timestamp <= ?")
            params.append(float(end_time))

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Count total matching rows
            count_sql = f"SELECT COUNT(*) FROM telemetry_logs{where_sql};"
            cursor.execute(count_sql, params)
            total_records = cursor.fetchone()[0]

            # Fetch page data
            data_sql = (
                f"SELECT id, timestamp, pid, metric_name, decoded_value, unit, raw_hex "
                f"FROM telemetry_logs{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?;"
            )
            cursor.execute(data_sql, params + [limit, offset])
            rows = cursor.fetchall()
            data = [dict(row) for row in rows]

        total_pages = (total_records + limit - 1) // limit if total_records > 0 else 0

        return {
            "page": page,
            "limit": limit,
            "total_records": total_records,
            "total_pages": total_pages,
            "data": data,
        }


    def get_latest_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Fetches the most recent record for each distinct PID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pid, metric_name, decoded_value, unit, timestamp, raw_hex
                FROM telemetry_logs
                WHERE id IN (
                    SELECT MAX(id) FROM telemetry_logs GROUP BY pid
                );
            """)
            rows = cursor.fetchall()
            return {row["pid"]: dict(row) for row in rows}

    def clear_database(self):
        """Clears all records from the telemetry_logs table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_logs;")
            cursor.execute("VACUUM;")
            conn.commit()
            logger.info("Cleared database telemetry records")
