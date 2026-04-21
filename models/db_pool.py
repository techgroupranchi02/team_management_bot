"""Shared MySQL connection pool for all models."""
from mysql.connector.pooling import MySQLConnectionPool

_pool = None


def init_pool(db_config, pool_size=10):
    """Initialize the global connection pool. Call once at app startup."""
    global _pool
    # Remove keys that pooling doesn't accept
    config = {k: v for k, v in db_config.items() if k not in ('pool_name', 'pool_size')}
    _pool = MySQLConnectionPool(
        pool_name="bot_pool",
        pool_size=pool_size,
        pool_reset_session=True,
        **config
    )


def get_pooled_connection():
    """Get a connection from the pool. Caller must close it (returns to pool)."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")
    return _pool.get_connection()
