"""SQLAlchemy ORM models for the Recession Risk Dashboard."""

import os
from datetime import datetime, date

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    Date, DateTime, Text, UniqueConstraint, Index, text
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# Engine / session setup
# ---------------------------------------------------------------------------

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DB_DIR, "recession_kpi.db")


def get_engine():
    os.makedirs(DB_DIR, exist_ok=True)
    return create_engine(f"sqlite:///{DB_PATH}", echo=False)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class KpiData(Base):
    """Time-series values for every KPI."""
    __tablename__ = "kpi_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kpi_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("kpi_id", "date", name="uq_kpi_date"),
        Index("ix_kpi_data_kpi_id_date", "kpi_id", "date"),
    )


class RecessionScore(Base):
    """Daily computed recession risk scores."""
    __tablename__ = "recession_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    score = Column(Float, nullable=False)
    band = Column(String, nullable=False)     # LOW | ELEVATED | HIGH | CRITICAL
    computed_at = Column(DateTime, default=datetime.utcnow)
    category_breakdown = Column(String, nullable=True)  # JSON: {"yield_curve": 0.45, ...} (0–1 scale)


class KpiSnapshot(Base):
    """Per-KPI values the live score actually used on a given day.

    Written alongside each live RecessionScore upsert (never by Time Machine
    or history reconstruction). Diffing two days' snapshots is the only exact
    answer to "what moved the score since yesterday" — as-of reconstruction
    from KpiData already contains later releases and revisions.
    """
    __tablename__ = "kpi_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    kpi_id = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    sub_score = Column(Float, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "kpi_id", name="uq_kpi_snapshot_date_kpi"),
        Index("ix_kpi_snapshot_date", "date"),
    )


class MLScore(Base):
    """Statsmodels Logistic Regression recession probability scores."""
    __tablename__ = "ml_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    logit_score = Column(Float, nullable=True)   # P(recession) × 100
    computed_at = Column(DateTime, default=datetime.utcnow)


class AlertLog(Base):
    """Audit log of sent alert emails."""
    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String, nullable=False)   # warning | critical
    score = Column(Float, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)


class AppConfig(Base):
    """Key-value settings overrides (persists user changes from Settings page)."""
    __tablename__ = "app_config"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class NberRecession(Base):
    """Cached FRED USRECM binary recession indicator (0 or 1 per month)."""
    __tablename__ = "nber_recessions"

    date = Column(Date, primary_key=True)
    in_recession = Column(Boolean, nullable=False)


class ReferenceSeries(Base):
    """Long-history benchmark inputs (kpi_config.yaml `reference_series:`).

    Kept apart from KpiData (would enter the composite score) and from
    NberRecession (feeds chart shading, which must stay 2005+).
    """

    __tablename__ = "reference_series"

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_key = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("series_key", "date", name="uq_reference_series_key_date"),
    )


class AiCommentary(Base):
    """Cached AI-generated commentary for categories and global outlook."""
    __tablename__ = "ai_commentary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(String, nullable=False)   # "global" | "yield_curve" | etc.
    as_of_date = Column(Date, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    commentary = Column(Text, nullable=False)
    model = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("category_id", "as_of_date", name="uq_commentary_category_date"),
    )


# ---------------------------------------------------------------------------
# Init helper
# ---------------------------------------------------------------------------

def _migrate_schema(eng):
    """Apply one-time schema migrations for columns that create_all() won't add."""
    with eng.connect() as conn:
        # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(recession_scores)"))]
        if "category_breakdown" not in cols:
            conn.execute(text("ALTER TABLE recession_scores ADD COLUMN category_breakdown TEXT"))
            conn.commit()
        # ai_commentary table is created via create_all() — no column migration needed


def init_db():
    """Create all tables if they don't exist yet, then apply schema migrations."""
    Base.metadata.create_all(engine)
    _migrate_schema(engine)


def get_session():
    return SessionLocal()
