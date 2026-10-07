"""Страница «Выручка и сегменты»: MRR, ARPU и разбивки по сегментам."""

from __future__ import annotations

import pathlib
import sys

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(_ROOT))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import lib  # noqa: E402

lib.page_config("Выручка и сегменты")


def render() -> None:
    """Отрисовать страницу выручки и сегментов."""
    st.title("Выручка и сегменты")
    if not lib.require_warehouse():
        return
    template = lib.theme_selector()
    f = lib.sidebar_filters()
    cte = f.users_cte()

    # ---- Headline монетизации --------------------------------------------- #
    mon = lib.query(f"""
        WITH {cte},
        u AS (SELECT * FROM dim_users JOIN fu USING (user_id))
        SELECT
            (SELECT coalesce(sum(e.event_value) FILTER (WHERE e.event_value>0),0)
             FROM fct_events e JOIN fu USING (user_id)
             WHERE e.is_purchase AND {f.date_clause('e.event_date')})           AS revenue,
            (SELECT count(*) FROM u WHERE is_paying)                            AS paying,
            (SELECT count(*) FROM u WHERE is_converted)                         AS converted,
            (SELECT count(*) FROM u WHERE is_churned_paid)                      AS churned
        """).iloc[0]
    arpu = mon["revenue"] / mon["paying"] if mon["paying"] else 0
    churn = mon["churned"] / mon["converted"] if mon["converted"] else 0
    lib.kpi_row(
        [
            ("Выручка (период)", lib.fmt_money(mon["revenue"]), "Сумма покупок"),
            ("Платящих сейчас", lib.fmt_int(mon["paying"]), "Активная подписка"),
            ("ARPU (платящие)", lib.fmt_money(arpu), "Выручка / платящих"),
            ("Отток платящих", lib.fmt_pct(churn), "Доля отписавшихся"),
        ]
    )
    st.divider()

    # ---- MRR по месяцам и планам ------------------------------------------ #
    st.subheader("MRR по месяцам в разрезе планов")
    mrr = lib.query(f"""
        WITH {cte}
        SELECT e.event_month AS month,
               coalesce(e.event_plan,'unknown') AS plan,
               sum(CASE WHEN e.event_value>0 THEN e.event_value ELSE 0 END) AS mrr
        FROM fct_events e JOIN fu USING (user_id)
        WHERE e.is_purchase AND {f.date_clause('e.event_date')}
          AND e.event_month <= (SELECT date_trunc('month', max(signup_date)) FROM dim_users)
        GROUP BY 1, 2 ORDER BY 1
        """)
    fig = px.bar(mrr, x="month", y="mrr", color="plan", color_discrete_map=lib.PLAN_COLORS)
    fig.update_layout(barmode="stack", yaxis_title="MRR, ₽", xaxis_title=None)
    st.plotly_chart(lib.style_fig(fig, template), width="stretch")

    # ---- Разбивки по сегментам -------------------------------------------- #
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Выручка по каналам")
        by_ch = lib.query(f"""
            WITH {cte}
            SELECT u.acquisition_channel AS channel,
                   round(sum(u.lifetime_revenue),2) AS revenue,
                   count(*) FILTER (WHERE u.is_paying) AS paying
            FROM dim_users u JOIN fu USING (user_id)
            GROUP BY 1 ORDER BY revenue DESC
            """)
        fig2 = px.bar(
            by_ch, x="channel", y="revenue", color="channel", color_discrete_sequence=lib.PALETTE
        )
        fig2.update_layout(showlegend=False, yaxis_title="Выручка, ₽", xaxis_title=None)
        st.plotly_chart(lib.style_fig(fig2, template), width="stretch")
    with c2:
        st.subheader("Конверсия free→paid по сегментам")
        by_seg = lib.query(f"""
            WITH {cte}
            SELECT u.behavior_segment AS segment,
                   round(count(*) FILTER (WHERE u.is_converted)::double / nullif(count(*),0),4) AS conv
            FROM dim_users u JOIN fu USING (user_id)
            GROUP BY 1 ORDER BY conv DESC
            """)
        fig3 = px.bar(
            by_seg, x="segment", y="conv", color="segment", color_discrete_sequence=lib.PALETTE
        )
        fig3.update_layout(
            showlegend=False, yaxis_tickformat=".0%", yaxis_title="Free→Paid", xaxis_title=None
        )
        st.plotly_chart(lib.style_fig(fig3, template), width="stretch")

    # ---- Топ гео ----------------------------------------------------------- #
    st.subheader("Выручка и платящие по гео")
    geo = lib.query(f"""
        WITH {cte}
        SELECT u.country AS country,
               count(*) AS users,
               count(*) FILTER (WHERE u.is_paying) AS paying,
               round(sum(u.lifetime_revenue),2) AS revenue
        FROM dim_users u JOIN fu USING (user_id)
        GROUP BY 1 ORDER BY revenue DESC
        """)
    st.dataframe(geo, width="stretch", hide_index=True)


render()
