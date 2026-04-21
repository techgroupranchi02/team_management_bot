"""Lightweight conversation analytics — logs key bot events."""
import mysql.connector
import time
import logging
import threading

logger = logging.getLogger(__name__)


class Analytics:
    def __init__(self, db_config):
        self.db_config = db_config
        self._ensure_table()
        # Batch buffer for non-blocking writes
        self._buffer = []
        self._lock = threading.Lock()

    def get_connection(self):
        try:
            from models.db_pool import get_pooled_connection
            return get_pooled_connection()
        except Exception:
            return mysql.connector.connect(**self.db_config)

    def _ensure_table(self):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_analytics (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL,
                    phone VARCHAR(20) DEFAULT NULL,
                    detail VARCHAR(255) DEFAULT NULL,
                    response_ms INT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_analytics_event (event_type),
                    INDEX idx_analytics_created (created_at)
                )
            """)
            conn.commit()
            logger.info("bot_analytics table ready")
        except Exception as e:
            logger.warning(f"bot_analytics migration skipped: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def log_event(self, event_type, phone=None, detail=None, response_ms=None):
        """Buffer an analytics event. Flushed periodically or when buffer is full."""
        with self._lock:
            self._buffer.append((event_type, phone, detail, response_ms))
            if len(self._buffer) >= 20:
                self._flush_locked()

    def flush(self):
        with self._lock:
            self._flush_locked()

    def _flush_locked(self):
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT INTO bot_analytics (event_type, phone, detail, response_ms) VALUES (%s, %s, %s, %s)",
                batch,
            )
            conn.commit()
        except Exception as e:
            logger.error(f"analytics flush error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
