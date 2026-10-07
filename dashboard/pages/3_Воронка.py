"""Страница «Воронка активации»: пошаговая конверсия signup → purchase."""

from __future__ import annotations

import pathlib
import sys

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(_ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import lib  # noqa: E402

lib.page_config("Воронка")

STEPS = ["signup", "login", "create_project", "run_report", "purchase"]
STEP_LABELS = {
    "signup": "Регистрация",
    "login": "Первый вход",
    "create_project": "Создал проект",
    "run_report": "Построил отчёт",
    "purchase": "Оплатил",
}


def _funnel_df(cte: str, f: lib.Filters, extra_user_cond: str = "TRUE"):
    """Посчитать вложенную воронку под текущими фильтрами."""
    flag_cols = ",\n".join(
        f"max(CASE WHEN e.event_name='{s}' THEN 1 ELSE 0 END) AS f{i}" for i, s in enumerate(STEPS)
    )
    flags = f"""
        WITH {cte},
        users AS (SELECT user_id FROM dim_users JOIN fu USING (user_id) WHERE {extra_user_cond}),
        ev AS (
            SELECT e.user_id, {flag_cols}
            FROM fct_events e JOIN users USING (user_id)
            WHERE {f.date_clause('e.event_date')}
            GROUP BY e.user_id
        )
        SELECT {", ".join(f"sum(f{i}) AS s{i}" for i in range(len(STEPS)))} FROM (
            SELECT user_id,
                {", ".join(f"CASE WHEN {' AND '.join(f'f{j}=1' for j in range(i+1))} THEN 1 ELSE 0 END AS f{i}" for i in range(len(STEPS)))}
            FROM ev
        )
    """
    row = lib.query(flags).iloc[0]
    return [int(row[f"s{i}"]) for i in range(len(STEPS))]


def render() -> None:
    """Отрисовать страницу воронки."""
    st.title("Воронка активации")
    st.caption("Строгая вложенность: каждый шаг учитывает выполнение всех предыдущих.")
    if not lib.require_warehouse():
        return
    template = lib.theme_selector()
    f = lib.sidebar_filters()
    cte = f.users_cte()

    counts = _funnel_df(cte, f)
    labels = [STEP_LABELS[s] for s in STEPS]

    fig = go.Figure(
        go.Funnel(
            y=labels,
            x=counts,
            textinfo="value+percent initial",
            marker=dict(color=lib.PALETTE[: len(STEPS)]),
        )
    )
    fig.update_layout(title="Активация: от регистрации до оплаты", height=460)
    st.plotly_chart(lib.style_fig(fig, template), width="stretch")

    # Таблица пошаговой конверсии.
    rows = []
    top = counts[0] or 1
    prev = None
    for label, n in zip(labels, counts, strict=False):
        rows.append(
            {
                "Шаг": label,
                "Пользователей": lib.fmt_int(n),
                "Конверсия с прошлого шага": lib.fmt_pct(n / prev) if prev else "—",
                "Конверсия от старта": lib.fmt_pct(n / top),
            }
        )
        prev = n
    st.dataframe(rows, width="stretch", hide_index=True)

    st.divider()
    st.subheader("Сравнение воронок по каналам привлечения")
    opts = lib.filter_options()
    channels = f.channels or opts["channels"]
    fig2 = go.Figure()
    for i, ch in enumerate(channels):
        ch_cte = lib.Filters(
            f.date_start, f.date_end, [ch], f.plans, f.countries, f.segments
        ).users_cte()
        ch_counts = _funnel_df(ch_cte, f)
        fig2.add_trace(
            go.Funnel(
                name=ch,
                y=labels,
                x=ch_counts,
                textinfo="percent initial",
                marker=dict(color=lib.PALETTE[i % len(lib.PALETTE)]),
            )
        )
    fig2.update_layout(title="Конверсия воронки по каналам", height=460)
    st.plotly_chart(lib.style_fig(fig2, template), width="stretch")


render()
