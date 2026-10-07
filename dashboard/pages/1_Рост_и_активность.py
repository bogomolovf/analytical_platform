"""Страница «Рост и активность»: приток пользователей, каналы, DAU/WAU/MAU."""

from __future__ import annotations

import pathlib
import sys

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(_ROOT))

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import lib  # noqa: E402

lib.page_config("Рост и активность")


def render() -> None:
    """Отрисовать страницу роста и активности."""
    st.title("Рост и активность")
    if not lib.require_warehouse():
        return
    template = lib.theme_selector()
    f = lib.sidebar_filters()
    cte = f.users_cte()

    # ---- Приток новых пользователей по неделям + канал --------------------- #
    st.subheader("Приток новых пользователей по каналам (недели)")
    acq = lib.query(f"""
        WITH {cte}
        SELECT date_trunc('week', u.signup_date)::date AS week,
               u.acquisition_channel AS channel,
               count(*) AS new_users
        FROM dim_users u JOIN fu USING (user_id)
        WHERE {f.date_clause('u.signup_date')}
        GROUP BY 1, 2 ORDER BY 1
        """)
    fig = px.bar(acq, x="week", y="new_users", color="channel", color_discrete_sequence=lib.PALETTE)
    fig.update_layout(barmode="stack", yaxis_title="Новые пользователи", xaxis_title=None)
    st.plotly_chart(lib.style_fig(fig, template), width="stretch")

    # ---- DAU / WAU / MAU --------------------------------------------------- #
    st.subheader("Активные пользователи: DAU / WAU / MAU")
    au = lib.query(f"""
        WITH {cte},
        uad AS (
            SELECT DISTINCT e.user_id, e.event_date
            FROM fct_events e JOIN fu USING (user_id)
            WHERE e.event_name NOT IN ('purchase','churn')
        ),
        d AS (SELECT date_day FROM dim_dates WHERE {f.date_clause('date_day')})
        SELECT d.date_day AS date,
            (SELECT count(DISTINCT user_id) FROM uad WHERE event_date = d.date_day) AS DAU,
            (SELECT count(DISTINCT user_id) FROM uad
                WHERE event_date BETWEEN d.date_day - INTERVAL 6 DAY AND d.date_day) AS WAU,
            (SELECT count(DISTINCT user_id) FROM uad
                WHERE event_date BETWEEN d.date_day - INTERVAL 27 DAY AND d.date_day) AS MAU
        FROM d ORDER BY d.date_day
        """)
    fig2 = go.Figure()
    for i, col in enumerate(["DAU", "WAU", "MAU"]):
        fig2.add_scatter(
            x=au["date"], y=au[col], name=col, line=dict(width=2, color=lib.PALETTE[i])
        )
    fig2.update_layout(yaxis_title="Пользователи", xaxis_title=None)
    st.plotly_chart(lib.style_fig(fig2, template), width="stretch")

    # ---- Сессии и события -------------------------------------------------- #
    c1, c2 = st.columns(2)
    daily = lib.query(f"""
        WITH {cte}
        SELECT e.event_date AS date,
               count(DISTINCT e.session_id) AS sessions,
               count(*) AS events
        FROM fct_events e JOIN fu USING (user_id)
        WHERE e.event_name NOT IN ('purchase','churn') AND {f.date_clause('e.event_date')}
        GROUP BY 1 ORDER BY 1
        """)
    with c1:
        st.subheader("Сессии в день")
        fig3 = px.line(daily, x="date", y="sessions")
        fig3.update_traces(line_color=lib.PALETTE[4])
        fig3.update_layout(yaxis_title="Сессии", xaxis_title=None)
        st.plotly_chart(lib.style_fig(fig3, template), width="stretch")
    with c2:
        st.subheader("Событий в день")
        fig4 = px.line(daily, x="date", y="events")
        fig4.update_traces(line_color=lib.PALETTE[1])
        fig4.update_layout(yaxis_title="События", xaxis_title=None)
        st.plotly_chart(lib.style_fig(fig4, template), width="stretch")

    # ---- Профиль сессий ---------------------------------------------------- #
    st.subheader("Профиль сессий по устройствам")
    sess = lib.query(f"""
        WITH {cte}
        SELECT s.device,
               count(*) AS sessions,
               round(avg(s.duration_seconds) / 60.0, 1) AS avg_minutes,
               round(avg(s.event_count), 1) AS avg_events
        FROM fct_sessions s JOIN fu USING (user_id)
        WHERE {f.date_clause('s.session_date')}
        GROUP BY 1 ORDER BY sessions DESC
        """)
    st.dataframe(sess, width="stretch", hide_index=True)


render()
