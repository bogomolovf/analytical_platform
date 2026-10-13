"""Загрузка сырых CSV-выгрузок в DuckDB (слой ``raw``).

Шаг E/L: сырые файлы из ``data/raw`` кладутся в таблицы ``raw_users`` и
``raw_events`` «как есть», без очистки - очистка происходит на слое staging.
"""

from __future__ import annotations

import duckdb

from src.config import Config


def load_raw(con: duckdb.DuckDBPyConnection, cfg: Config) -> dict[str, int]:
    """Загрузить сырые CSV в таблицы ``raw_*`` внутри DuckDB.

    Читаем через ``read_csv_auto`` с явным ``all_varchar`` там, где важно
    сохранить «грязь» (пустые строки, странные значения) до слоя staging,
    где выполняется типизация.

    Args:
        con: Открытое соединение DuckDB.
        cfg: Конфигурация проекта (нужны пути к сырым файлам).

    Returns:
        Словарь ``{имя_таблицы: число_строк}``.
    """
    raw_dir = cfg.raw_dir
    users_csv = (raw_dir / "raw_users.csv").as_posix()
    events_csv = (raw_dir / "raw_events.csv").as_posix()

    con.execute(f"""
        CREATE OR REPLACE TABLE raw_users AS
        SELECT * FROM read_csv_auto('{users_csv}', header=true, sample_size=-1);
        """)
    con.execute(f"""
        CREATE OR REPLACE TABLE raw_events AS
        SELECT * FROM read_csv_auto('{events_csv}', header=true, sample_size=-1);
        """)

    counts = {
        "raw_users": con.execute("SELECT count(*) FROM raw_users").fetchone()[0],
        "raw_events": con.execute("SELECT count(*) FROM raw_events").fetchone()[0],
    }
    return counts
