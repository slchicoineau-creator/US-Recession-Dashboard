"""Shared pytest fixtures for the recession-dashboard test suite.

Two DB modes:
- `real_session`: read-only access to data/recession_kpi.db (the live DB) for
  audit-style tests (threshold sweep, staleness audit, time-machine regression).
- `tmp_session`: a temp SQLite file with the project schema, for unit tests
  that need to seed synthetic data.

Adds the project root to sys.path so backend/* imports work.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Stub SMTP password so alerter does not try to send real email if any code path
# hits it during tests.
os.environ.setdefault("ALERT_EMAIL_PASSWORD", "")


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def kpi_config() -> dict:
    import yaml
    with open(PROJECT_ROOT / "kpi_config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def real_db_path() -> Path:
    return PROJECT_ROOT / "data" / "recession_kpi.db"


@pytest.fixture(scope="session")
def real_session(real_db_path):
    """Read-only session against the live DB. Tests must NOT commit."""
    if not real_db_path.exists():
        pytest.skip(f"Live DB not found at {real_db_path}")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine(f"sqlite:///{real_db_path}", echo=False)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    sess = Session()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


@pytest.fixture
def tmp_session(tmp_path, monkeypatch):
    """Fresh temp SQLite DB with the full project schema. Each test gets its own."""
    tmp_db = tmp_path / "test.db"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import backend.models as models

    eng = create_engine(f"sqlite:///{tmp_db}", echo=False)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)

    # Rebind module globals so any code that imports `backend.models.SessionLocal`
    # or `backend.models.engine` will see the temp DB.
    monkeypatch.setattr(models, "engine", eng)
    monkeypatch.setattr(models, "SessionLocal", Session)
    models.Base.metadata.create_all(eng)

    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        eng.dispose()


def _frequency_window_days(freq: str) -> int:
    """Mirrors backend.fetcher.check_staleness windows."""
    return {"daily": 15, "weekly": 60, "monthly": 95, "quarterly": 250}.get(freq, 95)


@pytest.fixture(scope="session")
def staleness_window():
    return _frequency_window_days
