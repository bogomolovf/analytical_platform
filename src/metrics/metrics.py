"""Слой продуктовых метрик.

Поверх витрин (marts) считаются ключевые продуктовые метрики и материализуются
в DuckDB как таблицы с префиксом ``metric_`` - дашборд затем просто читает их.

Определения всех метрик описаны в ``METRICS.md``. Считаются:

* ``metric_active_users``     - DAU / WAU / MAU и stickiness (DAU/MAU);
* ``metric_retention_dayn``   - day-N retention по всей базе;
* ``metric_activation_funnel``- воронка активации со ступенчатой конверсией;
* ``metric_mrr``              - MRR по месяцам и планам, число платящих;
* ``metric_segments``         - разбивка пользователей/выручки по сегментам;
* ``metric_summary``          - единая строка headline-KPI (в т.ч. North Star).
"""

from __future__ import annotations

import duckdb
import pandas as pd

from src.config import Config, load_config


# --------------------------------------------------------------------------- #
# DAU / WAU / MAU / stickiness
# --------------------------------------------------------------------------- #
def build_active_users(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """DAU, WAU (скользящее 7д), MAU (скользящее 28д) и stickiness = DAU/MAU."""
    con.execute("""
        CREATE OR REPLACE TABLE metric_active_users AS
        WITH user_active_days AS (
            SELECT DISTINCT user_id, event_date
            FROM fct_events
            WHERE event_name NOT IN ('purchase', 'churn')
        ),
        dau AS (
            SELECT event_date AS activity_date, count(DISTINCT user_id) AS dau
            FROM user_active_days GROUP BY event_date
        ),
        wau AS (
            SELECT d.date_day AS activity_date, count(DISTINCT u.user_id) AS wau
            FROM dim_dates d
            JOIN user_active_days u
              ON u.event_date BETWEEN d.date_day - INTERVAL 6 DAY AND d.date_day
            GROUP BY d.date_day
        ),
        mau AS (
            SELECT d.date_day AS activity_date, count(DISTINCT u.user_id) AS mau
            FROM dim_dates d
            JOIN user_active_days u
              ON u.event_date BETWEEN d.date_day - INTERVAL 27 DAY AND d.date_day
            GROUP BY d.date_day
        )
        SELECT
            d.date_day AS activity_date,
            coalesce(dau.dau, 0)  AS dau,
            coalesce(wau.wau, 0)  AS wau,
            coalesce(mau.mau, 0)  AS mau,
            round(coalesce(dau.dau, 0)::double / nullif(mau.mau, 0), 4) AS stickiness
        FROM dim_dates d
        LEFT JOIN dau ON d.date_day = dau.activity_date
        LEFT JOIN wau ON d.date_day = wau.activity_date
        LEFT JOIN mau ON d.date_day = mau.activity_date
        ORDER BY d.date_day
        """)
    return con.execute("SELECT * FROM metric_active_users").df()


# --------------------------------------------------------------------------- #
# Day-N retention
# --------------------------------------------------------------------------- #
def build_retention_dayn(con: duckdb.DuckDBPyConnection, days: list[int]) -> pd.DataFrame:
    """Day-N retention по всей базе.

    Для каждого N доля пользователей, вернувшихся ровно на N-й день после
    регистрации, среди тех, кто «дожил» до этого дня (signup_date + N в окне).
    """
    days_list = ", ".join(str(int(d)) for d in days)
    con.execute(f"""
        CREATE OR REPLACE TABLE metric_retention_dayn AS
        WITH max_date AS (SELECT max(event_date) AS d FROM fct_events),
        user_offsets AS (
            SELECT DISTINCT
                e.user_id,
                date_diff('day', u.signup_date, e.event_date) AS day_number
            FROM fct_events e
            JOIN dim_users u USING (user_id)
            WHERE e.event_name NOT IN ('purchase', 'churn')
        ),
        targets AS (SELECT unnest([{days_list}]) AS day_number),
        eligible AS (
            SELECT t.day_number, count(*) AS eligible_users
            FROM dim_users u
            CROSS JOIN targets t
            CROSS JOIN max_date m
            WHERE u.signup_date + t.day_number * INTERVAL 1 DAY <= m.d
            GROUP BY t.day_number
        ),
        retained AS (
            SELECT day_number, count(DISTINCT user_id) AS retained_users
            FROM user_offsets
            WHERE day_number IN ({days_list})
            GROUP BY day_number
        )
        SELECT
            e.day_number,
            e.eligible_users,
            coalesce(r.retained_users, 0) AS retained_users,
            round(coalesce(r.retained_users, 0)::double
                  / nullif(e.eligible_users, 0), 4) AS retention_rate
        FROM eligible e
        LEFT JOIN retained r USING (day_number)
        ORDER BY e.day_number
        """)
    return con.execute("SELECT * FROM metric_retention_dayn").df()


# --------------------------------------------------------------------------- #
# Воронка активации
# --------------------------------------------------------------------------- #
def build_activation_funnel(con: duckdb.DuckDBPyConnection, steps: list[str]) -> pd.DataFrame:
    """Воронка активации со строгой вложенностью шагов.

    Пользователь «дошёл» до шага k, только если совершил все предыдущие шаги
    (1..k) хотя бы раз. Это гарантирует монотонно убывающую воронку и корректную
    пошаговую конверсию - как в продуктовой аналитике.
    """
    # Булевы флаги «совершал ли пользователь событие-шаг».
    flag_cols = ",\n            ".join(
        f"max(CASE WHEN event_name = '{s}' THEN 1 ELSE 0 END) AS f{i}" for i, s in enumerate(steps)
    )
    flags_sql = f"""
        SELECT user_id,
            {flag_cols}
        FROM fct_events
        GROUP BY user_id
    """

    rows = []
    prev = None
    top = None
    for k, step in enumerate(steps):
        # Условие «дошёл до шага k» = все флаги 0..k равны 1.
        cond = " AND ".join(f"f{j} = 1" for j in range(k + 1))
        n = con.execute(f"SELECT count(*) FROM ({flags_sql}) t WHERE {cond}").fetchone()[0]
        n = int(n)
        top = top or n or 1
        rows.append(
            {
                "step_order": k + 1,
                "step": step,
                "users": n,
                "conv_from_prev": round(n / prev, 4) if prev else 1.0,
                "conv_from_top": round(n / top, 4),
            }
        )
        prev = n
    df = pd.DataFrame(rows)
    con.execute("CREATE OR REPLACE TABLE metric_activation_funnel AS SELECT * FROM df")
    return df


# --------------------------------------------------------------------------- #
# MRR по месяцам и планам
# --------------------------------------------------------------------------- #
def build_mrr(con: duckdb.DuckDBPyConnection, analysis_end: str) -> pd.DataFrame:
    """MRR по месяцам и планам.

    Каждая активная подписка порождает одно списание в месяц, поэтому сумма
    положительных покупок за месяц = MRR. Дополнительно - число платящих.
    Хвост за границей окна анализа (неполные месяцы) отсекается.
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE metric_mrr AS
        SELECT
            event_month,
            coalesce(event_plan, 'unknown')                      AS plan,
            sum(CASE WHEN event_value > 0 THEN event_value ELSE 0 END) AS mrr,
            count(DISTINCT user_id)                              AS paying_users
        FROM fct_events
        WHERE is_purchase
          AND event_month <= date_trunc('month', DATE '{analysis_end}')
        GROUP BY event_month, coalesce(event_plan, 'unknown')
        ORDER BY event_month, plan
        """)
    return con.execute("SELECT * FROM metric_mrr").df()


# --------------------------------------------------------------------------- #
# Разбивка по сегментам
# --------------------------------------------------------------------------- #
def build_segments(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Пользователи, платящие, конверсия и выручка по сегментам.

    Сегменты: канал привлечения, план, гео. Единая «длинная» таблица.
    """
    con.execute("""
        CREATE OR REPLACE TABLE metric_segments AS
        WITH base AS (
            SELECT 'channel' AS segment_type, acquisition_channel AS segment_value,
                   user_id, is_converted, is_paying, lifetime_revenue FROM dim_users
            UNION ALL
            SELECT 'plan', current_plan, user_id, is_converted, is_paying, lifetime_revenue FROM dim_users
            UNION ALL
            SELECT 'country', country, user_id, is_converted, is_paying, lifetime_revenue FROM dim_users
        )
        SELECT
            segment_type,
            segment_value,
            count(*)                                              AS users,
            sum(CASE WHEN is_converted THEN 1 ELSE 0 END)         AS converted_users,
            sum(CASE WHEN is_paying THEN 1 ELSE 0 END)            AS paying_users,
            round(sum(CASE WHEN is_converted THEN 1 ELSE 0 END)::double
                  / nullif(count(*), 0), 4)                       AS conversion_rate,
            round(sum(lifetime_revenue), 2)                       AS revenue
        FROM base
        GROUP BY segment_type, segment_value
        ORDER BY segment_type, revenue DESC
        """)
    return con.execute("SELECT * FROM metric_segments").df()


# --------------------------------------------------------------------------- #
# Единая строка headline-KPI
# --------------------------------------------------------------------------- #
def build_summary(con: duckdb.DuckDBPyConnection, analysis_end: str) -> pd.DataFrame:
    """Свод headline-метрик, включая North Star (WAU на дату окончания окна).

    «Текущие» значения берутся на референсную дату ``analysis_end`` (конец окна
    генерации), а не на самый последний таймстемп - так KPI не искажаются
    разреженным хвостом поздних служебных событий.
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE metric_summary AS
        WITH u AS (SELECT * FROM dim_users),
        totals AS (
            SELECT
                count(*)                                                  AS total_users,
                sum(CASE WHEN is_converted THEN 1 ELSE 0 END)             AS converted_users,
                sum(CASE WHEN is_paying THEN 1 ELSE 0 END)                AS paying_users,
                sum(CASE WHEN is_churned_paid THEN 1 ELSE 0 END)          AS churned_paid_users,
                round(sum(lifetime_revenue), 2)                           AS total_revenue
            FROM u
        ),
        nsm AS (  -- North Star = WAU на дату окончания окна анализа
            SELECT wau AS north_star_wau, stickiness AS latest_stickiness
            FROM metric_active_users
            WHERE activity_date = DATE '{analysis_end}'
        ),
        avgs AS (
            SELECT round(avg(dau), 0) AS avg_dau, round(avg(mau), 0) AS avg_mau
            FROM metric_active_users
            WHERE activity_date <= DATE '{analysis_end}'
        ),
        latest_mrr AS (  -- последний полный месяц окна
            SELECT sum(mrr) AS current_mrr
            FROM metric_mrr
            WHERE event_month = date_trunc('month', DATE '{analysis_end}')
        )
        SELECT
            t.total_users,
            t.converted_users,
            t.paying_users,
            round(t.converted_users::double / nullif(t.total_users, 0), 4) AS free_to_paid_rate,
            round(t.churned_paid_users::double / nullif(t.converted_users, 0), 4) AS paid_churn_rate,
            t.total_revenue,
            lm.current_mrr,
            n.north_star_wau,
            n.latest_stickiness,
            a.avg_dau,
            a.avg_mau
        FROM totals t, nsm n, avgs a, latest_mrr lm
        """)
    return con.execute("SELECT * FROM metric_summary").df()


# --------------------------------------------------------------------------- #
# Оркестрация
# --------------------------------------------------------------------------- #
def build_metrics(cfg: Config) -> dict[str, pd.DataFrame]:
    """Построить все metric_-таблицы поверх витрин в существующем warehouse.

    Returns:
        Словарь ``{имя_метрики: DataFrame}``.
    """
    analysis_end = str(cfg.generator["end_date"])
    con = duckdb.connect(cfg.warehouse_path.as_posix())
    try:
        result = {
            "active_users": build_active_users(con),
            "retention_dayn": build_retention_dayn(con, cfg.metrics["retention_days"]),
            "activation_funnel": build_activation_funnel(con, cfg.metrics["activation_funnel"]),
            "mrr": build_mrr(con, analysis_end),
            "segments": build_segments(con),
        }
        # summary зависит от active_users и mrr - считаем последним.
        result["summary"] = build_summary(con, analysis_end)
    finally:
        con.close()
    return result


def main() -> None:
    """CLI: построить метрики и напечатать headline-сводку."""
    import argparse

    parser = argparse.ArgumentParser(description="Расчёт продуктовых метрик.")
    parser.add_argument("--config", default=None, help="Путь к config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    result = build_metrics(cfg)
    summary = result["summary"].iloc[0]
    print("[metrics] метрики рассчитаны и материализованы (metric_*).")
    print(f"[metrics] пользователей:        {int(summary['total_users']):,}")
    print(f"[metrics] платящих:             {int(summary['paying_users']):,}")
    print(f"[metrics] free->paid:           {summary['free_to_paid_rate']:.1%}")
    print(f"[metrics] отток платящих:       {summary['paid_churn_rate']:.1%}")
    print(f"[metrics] North Star (WAU):     {int(summary['north_star_wau']):,}")
    print(f"[metrics] текущий MRR:          {summary['current_mrr']:,.0f} ₽")
    print(f"[metrics] выручка всего:         {summary['total_revenue']:,.0f} ₽")


if __name__ == "__main__":
    main()
