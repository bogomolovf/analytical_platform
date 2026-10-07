"""Тесты ELT-пайплайна и data-quality проверок."""

from __future__ import annotations

import duckdb

from src.config import Config, load_config
from src.pipeline.runner import (
    Model,
    discover_models,
    run_tests,
    topological_order,
)

EXPECTED_MODELS = {
    "stg_users",
    "stg_events",
    "dim_users",
    "dim_dates",
    "fct_events",
    "fct_sessions",
    "agg_daily_activity",
    "cohort_retention",
}


def test_all_models_materialized(con: duckdb.DuckDBPyConnection) -> None:
    """Все ожидаемые модели существуют как таблицы и непусты."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert tables >= EXPECTED_MODELS
    for model in EXPECTED_MODELS:
        rows = con.execute(f"SELECT count(*) FROM {model}").fetchone()[0]
        assert rows > 0, f"модель {model} пустая"


def test_dq_tests_all_pass(built_warehouse: Config) -> None:
    """Все data-quality тесты проходят на собранном warehouse."""
    con = duckdb.connect(built_warehouse.warehouse_path.as_posix(), read_only=True)
    try:
        results = run_tests(con, built_warehouse.root / "sql")
    finally:
        con.close()
    assert results, "не найдено ни одного DQ-теста"
    failed = [t.name for t in results if not t.passed]
    assert not failed, f"провалены DQ-тесты: {failed}"


def test_staging_dedup_and_cleaning(con: duckdb.DuckDBPyConnection) -> None:
    """Staging снимает дубликаты и чистит грязь."""
    # Уникальность user_id в stg_users.
    dup_users = con.execute(
        "SELECT count(*) FROM (SELECT user_id FROM stg_users GROUP BY user_id HAVING count(*)>1)"
    ).fetchone()[0]
    assert dup_users == 0
    # Нет отрицательных сумм покупок после очистки.
    neg = con.execute(
        "SELECT count(*) FROM fct_events WHERE event_name='purchase' AND event_value<0"
    ).fetchone()[0]
    assert neg == 0
    # Гео/устройство не содержат NULL (заменены на 'unknown').
    nulls = con.execute(
        "SELECT count(*) FROM dim_users WHERE country IS NULL OR device IS NULL"
    ).fetchone()[0]
    assert nulls == 0


def test_referential_integrity(con: duckdb.DuckDBPyConnection) -> None:
    """Каждый user_id из fct_events присутствует в dim_users."""
    orphans = con.execute("""
        SELECT count(*) FROM (
            SELECT e.user_id FROM fct_events e
            LEFT JOIN dim_users u USING (user_id)
            WHERE u.user_id IS NULL
        )
        """).fetchone()[0]
    assert orphans == 0


def test_topological_order_respects_deps() -> None:
    """Топологическая сортировка ставит зависимости раньше зависимых."""
    cfg = load_config()
    models = discover_models(cfg, cfg.root / "sql")
    ordered = topological_order(models)
    positions = {m.name: i for i, m in enumerate(ordered)}
    for m in models:
        for dep in m.refs:
            if dep in positions:
                assert positions[dep] < positions[m.name]


def test_topological_order_detects_cycle() -> None:
    """Цикл зависимостей приводит к ошибке."""
    import pytest

    a = Model("a", "marts", None, "select * from {{ ref('b') }}")
    b = Model("b", "marts", None, "select * from {{ ref('a') }}")
    with pytest.raises(ValueError):
        topological_order([a, b])
