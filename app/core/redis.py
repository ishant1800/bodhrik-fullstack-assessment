import logging

import redis

from app.core.config import settings

logger = logging.getLogger("bodhrik.redis")

# Global Redis client connection pool
_redis_pool: redis.ConnectionPool | None = None


def get_redis_pool() -> redis.ConnectionPool:
    """Initialize or return the global Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=5.0,
            retry_on_timeout=True,
        )
    return _redis_pool


def get_redis_client() -> redis.Redis:
    """Return a thread-safe Redis client instance backed by the connection pool."""
    pool = get_redis_pool()
    return redis.Redis(connection_pool=pool)


def check_redis_connection() -> bool:
    """Safely verify Redis connectivity without leaking internals or credentials."""
    try:
        client = get_redis_client()
        return bool(client.ping())
    except (redis.RedisError, OSError, Exception) as exc:
        logger.warning(
            "Redis connectivity check failed: %s (type: %s)",
            str(exc),
            type(exc).__name__,
        )
        return False


def close_redis_connection() -> None:
    """Close the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        try:
            _redis_pool.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error disconnecting Redis pool: %s", exc)
        finally:
            _redis_pool = None
