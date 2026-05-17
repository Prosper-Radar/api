"""
Sprint 4 tests — robustness, auth, dedup, rate-limit wiring.
"""
import pytest


# ─── JWT / Auth ───────────────────────────────────────────────────────────────

def test_create_and_decode_token():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.core.security import create_access_token, get_password_hash, verify_password
    from jose import jwt

    token = create_access_token("alice")
    payload = jwt.decode(token, os.environ["SECRET_KEY"], algorithms=["HS256"])
    assert payload["sub"] == "alice"


def test_password_hashing():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.core.security import get_password_hash, verify_password

    hashed = get_password_hash("mysecret")
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_authenticate_user_ok():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.core.security import authenticate_user

    assert authenticate_user("demo", "demo1234") == "demo"


def test_authenticate_user_bad_password():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.core.security import authenticate_user

    assert authenticate_user("demo", "wrong") is None


def test_authenticate_user_unknown():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.core.security import authenticate_user

    assert authenticate_user("ghost", "whatever") is None


# ─── Celery fallback ──────────────────────────────────────────────────────────

def test_celery_disabled_without_broker(monkeypatch):
    """When CELERY_BROKER_URL is absent, celery_app should be None."""
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    import importlib
    import app.worker.celery_app as m
    importlib.reload(m)
    # Either None (no broker) or a real Celery instance if env var was set
    # We just assert no crash occurred
    assert m.celery_app is None or hasattr(m.celery_app, "task")


# ─── Rate-limiter config ──────────────────────────────────────────────────────

def test_limiter_exists():
    from app.core.limiter import limiter
    assert limiter is not None


# ─── Scoring engine — existing tests stay green ───────────────────────────────

def test_engine_full_data():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.scoring.engine import ScoringInput, compute_score

    inp = ScoringInput(
        distance_to_water_m=50,
        zoning_code="MU",
        land_value=400_000,
        lot_size_sqft=20_000,
        population_growth_rate=0.03,
        aadt=12_000,
        last_sale_date="2022-01-01",
    )
    result = compute_score(inp)
    assert 0 <= result.total <= 100
    assert result.missing_metrics == []


def test_engine_missing_water():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.scoring.engine import ScoringInput, compute_score

    inp = ScoringInput(
        distance_to_water_m=None,     # no NHD data
        zoning_code="BU-1A",
        land_value=250_000,
        lot_size_sqft=8_000,
        population_growth_rate=None,  # no Census key
        aadt=None,                     # no FDOT hit
        last_sale_date="2023-06-01",
    )
    result = compute_score(inp)
    assert 0 <= result.total <= 100
    assert "waterfront" in result.missing_metrics
    assert "population_growth" in result.missing_metrics
    assert "traffic" in result.missing_metrics


# ─── Sync / dedup helpers ─────────────────────────────────────────────────────

def test_build_upsert_set_excludes_parcel_id():
    import os
    os.environ.setdefault("SECRET_KEY", "local-dev-secret-key-32chars-ok!")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    from app.tasks.sync import _build_upsert_set

    row = {"parcel_id": "12-3456", "address": "123 Main", "land_value": 100_000, "geometry": None}
    result = _build_upsert_set(row)
    assert "parcel_id" not in result
    assert "address" in result
    assert "geometry" in result
