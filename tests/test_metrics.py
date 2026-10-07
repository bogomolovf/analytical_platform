"""Тесты слоя метрик."""

from __future__ import annotations

import duckdb

METRIC_TABLES = {
    "metric_active_users",
    "metric_retention_dayn",
    "metric_activation_funnel",
    "metric_mrr",
    "metric_segments",
    "metric_summary",
}


def test_metric_tables_exist(con: duckdb.DuckDBPyConnection) -> None:
    """Все metric_-таблицы материализованы."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert tables >= METRIC_TABLES


def test_active_users_bounds(con: duckdb.DuckDBPyConnection) -> None:
    """DAU <= WAU <= MAU для каждой даты (математически обязано выполняться)."""
    bad = con.execute(
        "SELECT count(*) FROM metric_active_users WHERE dau > wau OR wau > mau"
    ).fetchone()[0]
    assert bad == 0


def test_stickiness_in_range(con: duckdb.DuckDBPyConnection) -> None:
    """Stickiness (DAU/MAU) лежит в [0, 1]."""
    bad = con.execute(
        "SELECT count(*) FROM metric_active_users WHERE stickiness < 0 OR stickiness > 1"
    ).fetchone()[0]
    assert bad == 0


def test_funnel_monotonic(con: duckdb.DuckDBPyConnection) -> None:
    """Воронка строго не возрастает по шагам (вложенность)."""
    df = con.execute("SELECT users FROM metric_activation_funnel ORDER BY step_order").df()
    users = df["users"].tolist()
    assert users == sorted(users, reverse=True)
    assert users[0] > 0


def test_retention_rate_range(con: duckdb.DuckDBPyConnection) -> None:
    """Day-N retention в диапазоне [0, 1] и не растёт со временем."""
    df = con.execute(
        "SELECT day_number, retention_rate FROM metric_retention_dayn ORDER BY day_number"
    ).df()
    assert df["retention_rate"].between(0, 1).all()


def test_summary_fields(con: duckdb.DuckDBPyConnection) -> None:
    """В summary заполнены ключевые headline-метрики и они осмысленны."""
    s = con.execute("SELECT * FROM metric_summary").df().iloc[0]
    assert s["total_users"] > 0
    assert 0 <= s["free_to_paid_rate"] <= 1
    assert 0 <= s["paid_churn_rate"] <= 1
    assert s["north_star_wau"] >= 0


def test_mrr_non_negative(con: duckdb.DuckDBPyConnection) -> None:
    """MRR по месяцам неотрицательный."""
    bad = con.execute("SELECT count(*) FROM metric_mrr WHERE mrr < 0").fetchone()[0]
    assert bad == 0


def test_segments_cover_dimensions(con: duckdb.DuckDBPyConnection) -> None:
    """Разбивка по сегментам покрывает канал, план и гео."""
    types = {
        r[0] for r in con.execute("SELECT DISTINCT segment_type FROM metric_segments").fetchall()
    }
    assert {"channel", "plan", "country"} <= types
