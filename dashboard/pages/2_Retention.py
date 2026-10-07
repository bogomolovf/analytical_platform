"""Страница «Retention»: когортная heatmap и кривая day-N удержания."""

from __future__ import annotations

import pathlib
import sys

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(_ROOT))

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import lib  # noqa: E402

lib.page_config("Retention")

MAX_WEEKS = 20  # горизонт когортной heatmap


def render() -> None:
    """Отрисовать страницу удержания."""
    st.title("Удержание (Retention)")
    if not lib.require_warehouse():
        return
    template = lib.theme_selector()
    f = lib.sidebar_filters()
    cte = f.users_cte()

    st.subheader("Когортная heatmap: недельное удержание")
    st.caption(
        "Строка — когорта по неделе регистрации, столбец — N недель с момента "
        "регистрации, значение — доля вернувшихся пользователей."
    )

    # Пересчёт когортного удержания под текущие фильтры.
    coh = lib.query(f"""
        WITH {cte},
        users AS (
            SELECT u.user_id, u.cohort_week
            FROM dim_users u JOIN fu USING (user_id)
            WHERE {f.date_clause('u.signup_date')}
        ),
        aw AS (
            SELECT DISTINCT e.user_id, date_trunc('week', e.event_timestamp)::date AS activity_week
            FROM fct_events e JOIN users USING (user_id)
            WHERE e.event_name NOT IN ('purchase','churn')
        ),
        ca AS (
            SELECT u.cohort_week,
                   date_diff('week', u.cohort_week, a.activity_week) AS week_number,
                   a.user_id
            FROM users u JOIN aw a USING (user_id)
            WHERE a.activity_week >= u.cohort_week
        ),
        size AS (SELECT cohort_week, count(*) AS n FROM users GROUP BY 1),
        ret AS (
            SELECT cohort_week, week_number, count(DISTINCT user_id) AS active
            FROM ca WHERE week_number <= {MAX_WEEKS} GROUP BY 1, 2
        )
        SELECT r.cohort_week, r.week_number, s.n AS cohort_users,
               round(r.active::double / nullif(s.n,0), 4) AS retention_rate
        FROM ret r JOIN size s USING (cohort_week)
        WHERE s.n >= 10
        ORDER BY r.cohort_week, r.week_number
        """)

    if coh.empty:
        st.info("Недостаточно данных для когортной heatmap при текущих фильтрах.")
    else:
        pivot = coh.pivot(index="cohort_week", columns="week_number", values="retention_rate")
        sizes = coh.groupby("cohort_week")["cohort_users"].first()
        y_labels = [f"{d}  (n={sizes[d]})" for d in pivot.index]
        heat = go.Figure(
            go.Heatmap(
                z=pivot.values * 100,
                x=[f"W{c}" for c in pivot.columns],
                y=y_labels,
                colorscale="Blues",
                zmin=0,
                zmax=100,
                colorbar=dict(title="%"),
                hovertemplate="Когорта %{y}<br>%{x}: %{z:.1f}%<extra></extra>",
            )
        )
        heat.update_layout(title="Weekly retention, %", height=560, yaxis_autorange="reversed")
        st.plotly_chart(lib.style_fig(heat, template), width="stretch")

    st.divider()

    # ---- Day-N retention curve -------------------------------------------- #
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Кривая day-N retention")
        dayn = lib.query(f"""
            WITH {cte},
            users AS (SELECT user_id, signup_date FROM dim_users JOIN fu USING (user_id)),
            offs AS (
                SELECT DISTINCT e.user_id,
                       date_diff('day', u.signup_date, e.event_date) AS day_number
                FROM fct_events e JOIN users u USING (user_id)
                WHERE e.event_name NOT IN ('purchase','churn')
            ),
            targets AS (SELECT unnest([1,3,7,14,30,60,90]) AS day_number),
            maxd AS (SELECT max(event_date) AS d FROM fct_events),
            elig AS (
                SELECT t.day_number, count(*) AS eligible
                FROM users u CROSS JOIN targets t CROSS JOIN maxd m
                WHERE u.signup_date + t.day_number * INTERVAL 1 DAY <= m.d
                GROUP BY 1
            ),
            ret AS (
                SELECT day_number, count(DISTINCT user_id) AS retained
                FROM offs WHERE day_number IN (1,3,7,14,30,60,90) GROUP BY 1
            )
            SELECT e.day_number,
                   round(coalesce(r.retained,0)::double / nullif(e.eligible,0), 4) AS retention_rate
            FROM elig e LEFT JOIN ret r USING (day_number) ORDER BY e.day_number
            """)
        fig = px.line(dayn, x="day_number", y="retention_rate", markers=True)
        fig.update_traces(line_color=lib.PALETTE[0])
        fig.update_layout(
            yaxis_tickformat=".0%",
            yaxis_title="Retention",
            xaxis_title="День с момента регистрации",
        )
        st.plotly_chart(lib.style_fig(fig, template), width="stretch")
    with c2:
        st.subheader("Retention по сегментам (day-7 и day-30)")
        seg = lib.query(f"""
            WITH {cte},
            users AS (SELECT user_id, signup_date, behavior_segment
                      FROM dim_users JOIN fu USING (user_id)),
            offs AS (
                SELECT DISTINCT e.user_id,
                       date_diff('day', u.signup_date, e.event_date) AS day_number
                FROM fct_events e JOIN users u USING (user_id)
                WHERE e.event_name NOT IN ('purchase','churn')
            )
            SELECT u.behavior_segment AS segment,
                   round(count(DISTINCT CASE WHEN o.day_number>=7 THEN o.user_id END)::double
                         / nullif(count(DISTINCT u.user_id),0), 4) AS d7,
                   round(count(DISTINCT CASE WHEN o.day_number>=30 THEN o.user_id END)::double
                         / nullif(count(DISTINCT u.user_id),0), 4) AS d30
            FROM users u LEFT JOIN offs o USING (user_id)
            GROUP BY 1 ORDER BY d30 DESC
            """)
        figs = go.Figure()
        figs.add_bar(x=seg["segment"], y=seg["d7"], name="≥ day-7", marker_color=lib.PALETTE[0])
        figs.add_bar(x=seg["segment"], y=seg["d30"], name="≥ day-30", marker_color=lib.PALETTE[2])
        figs.update_layout(barmode="group", yaxis_tickformat=".0%", yaxis_title="Доля вернувшихся")
        st.plotly_chart(lib.style_fig(figs, template), width="stretch")


render()
