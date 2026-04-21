"""Persistent bot sessions for user state (active_client, property selections, contexts)."""
import mysql.connector
import json
import time
import logging

logger = logging.getLogger(__name__)


class BotSession:
    def __init__(self, db_config):
        self.db_config = db_config
        self._ensure_table()

    def get_connection(self):
        try:
            from models.db_pool import get_pooled_connection
            return get_pooled_connection()
        except Exception:
            return mysql.connector.connect(**self.db_config)

    # ── schema ──────────────────────────────────────────────
    def _ensure_table(self):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_sessions (
                    phone VARCHAR(20) PRIMARY KEY,
                    active_client_id INT DEFAULT NULL,
                    property_selections TEXT DEFAULT NULL,
                    context_data TEXT DEFAULT NULL,
                    context_ts DOUBLE DEFAULT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("bot_sessions table ready")
        except Exception as e:
            logger.warning(f"bot_sessions migration skipped: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── active client ───────────────────────────────────────
    def get_active_client(self, phone):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT active_client_id FROM bot_sessions WHERE phone = %s",
                (phone,),
            )
            row = cursor.fetchone()
            return row['active_client_id'] if row else None
        except Exception as e:
            logger.error(f"get_active_client error: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def set_active_client(self, phone, client_id):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO bot_sessions (phone, active_client_id)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE active_client_id = VALUES(active_client_id)""",
                (phone, client_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"set_active_client error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── property selections ─────────────────────────────────
    def get_property_selections(self, phone):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT property_selections FROM bot_sessions WHERE phone = %s",
                (phone,),
            )
            row = cursor.fetchone()
            if row and row['property_selections']:
                return json.loads(row['property_selections'])
            return None
        except Exception as e:
            logger.error(f"get_property_selections error: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def set_property_selections(self, phone, selections):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            data = json.dumps(selections) if selections else None
            cursor.execute(
                """INSERT INTO bot_sessions (phone, property_selections)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE property_selections = VALUES(property_selections)""",
                (phone, data),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"set_property_selections error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def clear_property_selections(self, phone):
        self.set_property_selections(phone, None)

    # ── context (conversation state) ────────────────────────
    def get_context(self, phone, ttl_seconds=1800):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT context_data, context_ts FROM bot_sessions WHERE phone = %s",
                (phone,),
            )
            row = cursor.fetchone()
            if not row or not row['context_data']:
                return None
            ts = row['context_ts'] or 0
            if time.time() - ts > ttl_seconds:
                # expired – clear it
                cursor2 = conn.cursor()
                cursor2.execute(
                    "UPDATE bot_sessions SET context_data = NULL, context_ts = NULL WHERE phone = %s",
                    (phone,),
                )
                conn.commit()
                return None
            return json.loads(row['context_data'])
        except Exception as e:
            logger.error(f"get_context error: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def set_context(self, phone, context_data):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            data = json.dumps(context_data) if context_data else None
            ts = time.time() if context_data else None
            cursor.execute(
                """INSERT INTO bot_sessions (phone, context_data, context_ts)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE context_data = VALUES(context_data), context_ts = VALUES(context_ts)""",
                (phone, data, ts),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"set_context error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def clear_context(self, phone):
        self.set_context(phone, None)
