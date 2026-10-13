"""Дашборд продуктовой аналитики - страница «Обзор».

North Star + KPI-плитки + headline-графики роста, удержания и выручки.
Запуск: ``streamlit run "dashboard/Приложение.py"`` (или ``make dashboard``).
"""

from __future__ import annotations

import pathlib
import sys

# Корень проекта в sys.path, чтобы работал импорт пакета dashboard под Streamlit.
_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(_ROOT))

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import lib  # noqa: E402

lib.page_config("Обзор")


def render() -> None:
    """Отрисовать страницу обзора."""
    st.title("Платформа продуктовой аналитики")
    st.caption(
        "Учебный дашборд на базе синтетических данных. "
        "События SaaS обрабатываются через ELT-пайплайн в DuckDB и превращаются в продуктовые метрики."
    )
    if not lib.require_warehouse():
        return

    template = lib.theme_selector()
    f = lib.sidebar_filters()
    cte = f.users_cte()

    # ---- Headline KPI (в разрезе фильтров и периода) --------------------- #
    kpi = lib.query(f"""
        WITH {cte},
        base AS (
            SELECT e.* FROM fct_events e JOIN fu USING (user_id)
            WHERE {f.date_clause('e.event_date')}
        ),
        users_in AS (SELECT user_id FROM dim_users JOIN fu USING (user_id))
        SELECT
            (SELECT count(*) FROM users_in)                                   AS total_users,
            (SELECT count(DISTINCT user_id) FROM base
                WHERE event_name NOT IN ('purchase','churn'))                 AS active_users,
            (SELECT count(*) FROM dim_users u JOIN fu USING (user_id)
                WHERE {f.date_clause('u.signup_date')})                       AS new_users,
            (SELECT count(*) FROM dim_users u JOIN fu USING (user_id)
                WHERE is_paying)                                              AS paying_users,
            (SELECT count(*) FROM dim_users u JOIN fu USING (user_id)
                WHERE is_converted)                                          AS converted_users,
            (SELECT coalesce(sum(CASE WHEN event_value>0 THEN event_value END),0)
                FROM base WHERE event_name='purchase')                        AS revenue
        """).iloc[0]

    conv_rate = kpi["converted_users"] / kpi["total_users"] if kpi["total_users"] else 0
    lib.kpi_row(
        [
            ("Всего пользователей", lib.fmt_int(kpi["total_users"]), "В выбранных сегментах"),
            (
                "Активные (период)",
                lib.fmt_int(kpi["active_users"]),
                "Уникальные активные за период",
            ),
            ("Новые регистрации", lib.fmt_int(kpi["new_users"]), "Signup внутри периода"),
            ("Платящих сейчас", lib.fmt_int(kpi["paying_users"]), "Активная подписка"),
            ("Free в Paid", lib.fmt_pct(conv_rate), "Доля сконвертировавшихся"),
            ("Выручка (период)", lib.fmt_money(kpi["revenue"]), "Сумма покупок за период"),
        ]
    )
    st.divider()

    # ---- North Star: WAU (недельные активные) ---------------------------- #
    au = lib.query(f"""
        WITH {cte},
        uad AS (
            SELECT DISTINCT e.user_id, e.event_date
            FROM fct_events e JOIN fu USING (user_id)
            WHERE e.event_name NOT IN ('purchase','churn')
        ),
        d AS (SELECT date_day FROM dim_dates WHERE {f.date_clause('date_day')})
        SELECT
            d.date_day AS activity_date,
            (SELECT count(DISTINCT user_id) FROM uad
                WHERE event_date BETWEEN d.date_day - INTERVAL 6 DAY AND d.date_day) AS wau,
            (SELECT count(DISTINCT user_id) FROM uad
                WHERE event_date = d.date_day) AS dau,
            (SELECT count(DISTINCT user_id) FROM uad
                WHERE event_date BETWEEN d.date_day - INTERVAL 27 DAY AND d.date_day) AS mau
        FROM d ORDER BY d.date_day
        """)

    left, right = st.columns([2, 1])
    with left:
        st.subheader("North Star - Weekly Active Users")
        fig = go.Figure()
        fig.add_scatter(
            x=au["activity_date"],
            y=au["wau"],
            name="WAU",
            mode="lines",
            fill="tozeroy",
            line=dict(width=2),
        )
        fig.add_scatter(x=au["activity_date"], y=au["dau"], name="DAU", line=dict(width=1.5))
        fig.update_layout(title="Динамика активной аудитории", yaxis_title="Пользователи")
        fig_au = lib.style_fig(fig, template)
        fig_au.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.12, x=0))
        st.plotly_chart(fig_au, width="stretch")
    with right:
        st.subheader("Stickiness")
        au_valid = au[au["mau"] > 0].copy()
        au_valid["stickiness"] = au_valid["dau"] / au_valid["mau"]
        avg_sticky = au_valid["stickiness"].mean() if len(au_valid) else 0
        st.metric(
            "DAU / MAU (среднее)",
            lib.fmt_pct(avg_sticky),
            help="Насколько часто активные возвращаются",
        )
        fig2 = go.Figure()
        fig2.add_scatter(
            x=au_valid["activity_date"],
            y=au_valid["stickiness"],
            line=dict(width=2, color=lib.PALETTE[2]),
        )
        fig2.update_layout(title="Stickiness во времени", yaxis_tickformat=".0%")
        st.plotly_chart(lib.style_fig(fig2, template), width="stretch")

    st.divider()

    # ---- Рост регистраций и выручка (месяц) ------------------------------ #
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Рост базы: новые пользователи по неделям")
        growth = lib.query(f"""
            WITH {cte}
            SELECT date_trunc('week', u.signup_date)::date AS week, count(*) AS new_users
            FROM dim_users u JOIN fu USING (user_id)
            WHERE {f.date_clause('u.signup_date')}
            GROUP BY 1 ORDER BY 1
            """)
        fig3 = px.bar(growth, x="week", y="new_users")
        fig3.update_traces(marker_color=lib.PALETTE[0])
        fig3.update_layout(yaxis_title="Новые пользователи", xaxis_title=None, showlegend=False)
        st.plotly_chart(lib.style_fig(fig3, template), width="stretch")
    with c2:
        st.subheader("Выручка по месяцам")
        rev = lib.query(f"""
            WITH {cte}
            SELECT e.event_month AS month,
                   sum(CASE WHEN e.event_value>0 THEN e.event_value ELSE 0 END) AS revenue
            FROM fct_events e JOIN fu USING (user_id)
            WHERE e.is_purchase AND {f.date_clause('e.event_date')}
              AND e.event_month <= (SELECT date_trunc('month', max(signup_date)) FROM dim_users)
            GROUP BY 1 ORDER BY 1
            """)
        fig4 = px.area(rev, x="month", y="revenue")
        fig4.update_traces(line_color=lib.PALETTE[2], fillcolor="rgba(84,162,75,0.25)")
        fig4.update_layout(yaxis_title="Выручка, ₽", xaxis_title=None, showlegend=False)
        st.plotly_chart(lib.style_fig(fig4, template), width="stretch")

    st.caption("Данные синтетические, генерация воспроизводима через seed в конфиге.")


render()
