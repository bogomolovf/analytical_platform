"""Общие фикстуры pytest.

Собираем маленький, но полноценный warehouse один раз на сессию тестов
(генерация → ELT → метрики) во временном каталоге, чтобы тесты были быстрыми
и не трогали основной ``data/``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import duckdb
import pytest

from src.config import Config, load_config
from src.generator.generate import generate, write_raw
from src.metrics.metrics import build_metrics
from src.pipeline.runner import build


def _small_config(tmp_path: Path) -> Config:
    """Копия дефолтного конфига с уменьшенным объёмом и временными путями."""
    base = load_config()
    raw = copy.deepcopy(base.raw)
    # Короткий период и меньше трафика -> быстрые тесты.
    raw["generator"]["start_date"] = "2024-09-01"
    raw["generator"]["end_date"] = "2024-11-30"
    raw["generator"]["base_daily_signups"] = 8
    # Абсолютные временные пути (перекрывают root / relative).
    raw["paths"]["raw_dir"] = str(tmp_path / "raw")
    raw["paths"]["warehouse"] = str(tmp_path / "warehouse.duckdb")
    return Config(raw=raw)


@pytest.fixture(scope="session")
def small_config(tmp_path_factory) -> Config:
    """Небольшой конфиг для тестов (сессионный)."""
    tmp = tmp_path_factory.mktemp("wh")
    return _small_config(tmp)


@pytest.fixture(scope="session")
def built_warehouse(small_config: Config) -> Config:
    """Полностью собранный warehouse: генерация + ELT + метрики."""
    data = generate(small_config)
    write_raw(data, small_config)
    build(small_config, run_dq_tests=True)
    build_metrics(small_config)
    return small_config


@pytest.fixture
def con(built_warehouse: Config) -> duckdb.DuckDBPyConnection:
    """Read-only соединение к собранному warehouse."""
    connection = duckdb.connect(built_warehouse.warehouse_path.as_posix(), read_only=True)
    yield connection
    connection.close()
