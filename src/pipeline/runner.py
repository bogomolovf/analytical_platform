"""Мини dbt-раннер поверх DuckDB.

Исполняет SQL-модели из каталога ``sql/`` слоями (staging → marts). Поддержан
упрощённый Jinja-подобный синтаксис:

* ``{{ ref('model_name') }}``      — ссылка на другую модель (таблицу);
* ``{{ source('raw', 'events') }}`` — ссылка на сырую таблицу (``raw_events``).

Раннер:

1. читает все ``.sql`` файлы из слоёв, перечисленных в конфиге;
2. строит граф зависимостей по вызовам ``ref()`` и топологически сортирует его;
3. материализует каждую модель как ``CREATE OR REPLACE TABLE`` в DuckDB;
4. отдельной командой прогоняет data-quality тесты из ``sql/tests``.

Так проект остаётся «в стиле dbt», но без внешних зависимостей и с прозрачной,
читаемой реализацией.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.config import Config
from src.pipeline.load import load_raw

_REF_RE = re.compile(r"{{\s*ref\(\s*['\"]([\w]+)['\"]\s*\)\s*}}")
_SOURCE_RE = re.compile(r"{{\s*source\(\s*['\"]([\w]+)['\"]\s*,\s*['\"]([\w]+)['\"]\s*\)\s*}}")


@dataclass
class Model:
    """Одна SQL-модель: имя, слой, путь и текст запроса."""

    name: str
    layer: str
    path: Path
    sql: str

    @property
    def refs(self) -> set[str]:
        """Множество моделей, на которые ссылается данная (через ``ref()``)."""
        return set(_REF_RE.findall(self.sql))


def _compile_sql(sql: str) -> str:
    """Развернуть ``ref()`` / ``source()`` в реальные имена таблиц DuckDB."""
    sql = _REF_RE.sub(lambda m: m.group(1), sql)
    sql = _SOURCE_RE.sub(lambda m: f"{m.group(1)}_{m.group(2)}", sql)
    return sql


def discover_models(cfg: Config, sql_root: Path) -> list[Model]:
    """Найти все модели в слоях, перечисленных в конфиге ``pipeline.layers``."""
    models: list[Model] = []
    for layer in cfg.pipeline["layers"]:
        layer_dir = sql_root / layer
        for path in sorted(layer_dir.glob("*.sql")):
            models.append(
                Model(name=path.stem, layer=layer, path=path, sql=path.read_text(encoding="utf-8"))
            )
    return models


def topological_order(models: list[Model]) -> list[Model]:
    """Отсортировать модели так, чтобы зависимости шли раньше зависимых.

    Классический алгоритм Кана. Учитываются только ``ref()`` на модели,
    которые реально присутствуют в проекте (ссылки на ``source`` игнорируются).

    Raises:
        ValueError: при обнаружении цикла зависимостей.
    """
    by_name = {m.name: m for m in models}
    indeg: dict[str, int] = {m.name: 0 for m in models}
    children: dict[str, list[str]] = {m.name: [] for m in models}

    for m in models:
        for dep in m.refs:
            if dep in by_name:
                indeg[m.name] += 1
                children[dep].append(m.name)

    queue = sorted(n for n, d in indeg.items() if d == 0)
    ordered: list[str] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for child in children[node]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
        queue.sort()

    if len(ordered) != len(models):
        cyclic = set(by_name) - set(ordered)
        raise ValueError(f"Обнаружен цикл зависимостей между моделями: {sorted(cyclic)}")
    return [by_name[n] for n in ordered]


def run_models(con: duckdb.DuckDBPyConnection, models: list[Model]) -> list[tuple[str, int, float]]:
    """Материализовать модели в порядке зависимостей.

    Returns:
        Список кортежей ``(имя_модели, число_строк, длительность_сек)``.
    """
    results: list[tuple[str, int, float]] = []
    for m in models:
        compiled = _compile_sql(m.sql)
        start = time.perf_counter()
        con.execute(f"CREATE OR REPLACE TABLE {m.name} AS\n{compiled}")
        rows = con.execute(f"SELECT count(*) FROM {m.name}").fetchone()[0]
        elapsed = time.perf_counter() - start
        results.append((m.name, rows, elapsed))
    return results


@dataclass
class TestResult:
    """Результат одного data-quality теста."""

    name: str
    failing_rows: int

    @property
    def passed(self) -> bool:
        """Тест пройден, если модель-тест вернула 0 нарушающих строк."""
        return self.failing_rows == 0


def run_tests(con: duckdb.DuckDBPyConnection, sql_root: Path) -> list[TestResult]:
    """Прогнать все data-quality тесты из ``sql/tests``.

    Каждый тестовый запрос возвращает строки, НАРУШАЮЩИЕ правило (уникальность,
    not null, ссылочная целостность). Пустой результат = тест пройден.
    """
    results: list[TestResult] = []
    tests_dir = sql_root / "tests"
    for path in sorted(tests_dir.glob("*.sql")):
        compiled = _compile_sql(path.read_text(encoding="utf-8"))
        failing = con.execute(f"SELECT count(*) FROM (\n{compiled}\n) _t").fetchone()[0]
        results.append(TestResult(name=path.stem, failing_rows=failing))
    return results


def build(
    cfg: Config,
    sql_root: Path | None = None,
    run_dq_tests: bool = True,
) -> dict:
    """Полный прогон ELT: raw → staging → marts (+ опционально DQ-тесты).

    Args:
        cfg: Конфигурация проекта.
        sql_root: Каталог с SQL-моделями (по умолчанию ``<root>/sql``).
        run_dq_tests: Выполнять ли data-quality тесты после сборки.

    Returns:
        Словарь со сводкой прогона (счётчики raw, модели, тесты).
    """
    sql_root = sql_root or (cfg.root / "sql")
    cfg.warehouse_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(cfg.warehouse_path.as_posix())
    try:
        raw_counts = load_raw(con, cfg)
        models = topological_order(discover_models(cfg, sql_root))
        model_results = run_models(con, models)
        tests = run_tests(con, sql_root) if run_dq_tests else []
    finally:
        con.close()

    return {
        "raw_counts": raw_counts,
        "models": model_results,
        "order": [m.name for m in models],
        "tests": tests,
    }


def main() -> None:
    """CLI: собрать витрины и напечатать сводку + результаты DQ-тестов."""
    import argparse
    import sys

    from src.config import load_config

    parser = argparse.ArgumentParser(description="Сборка ELT-витрин в DuckDB.")
    parser.add_argument("--config", default=None, help="Путь к config.yaml")
    parser.add_argument("--no-tests", action="store_true", help="Пропустить DQ-тесты")
    args = parser.parse_args()

    cfg = load_config(args.config)
    summary = build(cfg, run_dq_tests=not args.no_tests)

    print("[build] raw:", summary["raw_counts"])
    print("[build] порядок моделей:", " -> ".join(summary["order"]))
    for name, rows, elapsed in summary["models"]:
        print(f"[build]   {name:<24} {rows:>10,} строк  ({elapsed:.2f}s)")

    failed = [t for t in summary["tests"] if not t.passed]
    for t in summary["tests"]:
        status = "PASS" if t.passed else f"FAIL ({t.failing_rows})"
        print(f"[test]   {t.name:<32} {status}")
    if failed:
        print(f"[test] ПРОВАЛЕНО тестов: {len(failed)}")
        sys.exit(1)
    print("[build] готово: витрины собраны, все DQ-тесты пройдены.")


if __name__ == "__main__":
    main()
