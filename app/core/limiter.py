"""
Rate limiter — powered by slowapi (Starlette-compatible).

Limits are intentionally generous for internal use. Tighten in prod.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
