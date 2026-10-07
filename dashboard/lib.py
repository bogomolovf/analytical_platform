"""Общие утилиты дашборда: доступ к DuckDB, фильтры, тема и переиспользуемые UI.

Дашборд читает витрины и metric_-таблицы из ``data/warehouse.duckdb`` в
read-only режиме. Все запросы кэшируются Streamlit по тексту SQL и параметрам
фильтров, поэтому переключение фильтров быстрое.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Корень проекта = на два уровня выше dashboard/lib.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.duckdb"

# Единая качественная палитра (контрастна и читаема в светлой и тёмной теме).
PALETTE = [
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#B279A2",
    "#FF9DA6",
    "#9D755D",
    "#EECA3B",
    "#BAB0AC",
]
PLAN_COLORS = {"free": "#BAB0AC", "pro": "#4C78A8", "enterprise": "#54A24B"}


# --------------------------------------------------------------------------- #
# Соединение и запросы
# --------------------------------------------------------------------------- #
def warehouse_exists() -> bool:
    """Есть ли собранный warehouse на диске."""
    return WAREHOUSE.exists()


@st.cache_resource(show_spinner=False)
def _connect() -> duckdb.DuckDBPyConnection:
    """Открыть read-only соединение к DuckDB (кэшируется на сессию)."""
    return duckdb.connect(WAREHOUSE.as_posix(), read_only=True)


@st.cache_data(show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Выполнить SQL и вернуть DataFrame (результат кэшируется)."""
    con = _connect()
    return con.execute(sql, list(params)).df()


# --------------------------------------------------------------------------- #
# Фильтры
# --------------------------------------------------------------------------- #
@dataclass
class Filters:
    """Состояние глобальных фильтров дашборда."""

    date_start: dt.date
    date_end: dt.date
    channels: list[str]
    plans: list[str]
    countries: list[str]
    segments: list[str]

    def users_cte(self) -> str:
        """SQL-фрагмент CTE ``fu`` — множество user_id, прошедших сегмент-фильтры."""
        conds = []
        if self.channels:
            vals = ", ".join(f"'{c}'" for c in self.channels)
            conds.append(f"acquisition_channel IN ({vals})")
        if self.plans:
            vals = ", ".join(f"'{p}'" for p in self.plans)
            conds.append(f"current_plan IN ({vals})")
        if self.countries:
            vals = ", ".join(f"'{c}'" for c in self.countries)
            conds.append(f"country IN ({vals})")
        if self.segments:
            vals = ", ".join(f"'{s}'" for s in self.segments)
            conds.append(f"behavior_segment IN ({vals})")
        where = " AND ".join(conds) if conds else "TRUE"
        return f"fu AS (SELECT user_id FROM dim_users WHERE {where})"

    def date_clause(self, col: str = "event_date") -> str:
        """SQL-условие по диапазону дат для указанной колонки."""
        return f"{col} BETWEEN DATE '{self.date_start}' AND DATE '{self.date_end}'"


@st.cache_data(show_spinner=False)
def filter_options() -> dict:
    """Доступные значения фильтров и границы дат (из витрин)."""
    con = _connect()
    opts = {
        "channels": con.execute("SELECT DISTINCT acquisition_channel FROM dim_users ORDER BY 1")
        .df()["acquisition_channel"]
        .tolist(),
        "plans": con.execute("SELECT DISTINCT current_plan FROM dim_users ORDER BY 1")
        .df()["current_plan"]
        .tolist(),
        "countries": con.execute("SELECT DISTINCT country FROM dim_users ORDER BY 1")
        .df()["country"]
        .tolist(),
        "segments": con.execute("SELECT DISTINCT behavior_segment FROM dim_users ORDER BY 1")
        .df()["behavior_segment"]
        .tolist(),
    }
    bounds = con.execute("SELECT min(signup_date), max(signup_date) FROM dim_users").fetchone()
    opts["min_date"] = bounds[0]
    opts["max_date"] = bounds[1]
    return opts


def sidebar_filters() -> Filters:
    """Отрисовать сайдбар с фильтрами и вернуть их состояние."""
    opts = filter_options()
    st.sidebar.header("Фильтры")

    date_range = st.sidebar.date_input(
        "Период",
        value=(opts["min_date"], opts["max_date"]),
        min_value=opts["min_date"],
        max_value=opts["max_date"],
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_start, date_end = date_range
    else:
        date_start, date_end = opts["min_date"], opts["max_date"]

    channels = st.sidebar.multiselect("Канал привлечения", opts["channels"])
    plans = st.sidebar.multiselect("План", opts["plans"])
    segments = st.sidebar.multiselect("Поведенческий сегмент", opts["segments"])
    countries = st.sidebar.multiselect("Гео", opts["countries"])

    st.sidebar.caption(
        "Пустой фильтр = все значения. Фильтры по сегментам применяются "
        "к пользователям, фильтр по периоду — к событиям."
    )
    return Filters(date_start, date_end, channels, plans, countries, segments)


# --------------------------------------------------------------------------- #
# Тема и оформление графиков
# --------------------------------------------------------------------------- #
def theme_selector() -> str:
    """Переключатель темы графиков; возвращает plotly-шаблон."""
    choice = st.sidebar.radio("Тема графиков", ["Авто", "Светлая", "Тёмная"], horizontal=True)
    return {"Авто": None, "Светлая": "plotly_white", "Тёмная": "plotly_dark"}[choice]


def style_fig(fig: go.Figure, template: str | None) -> go.Figure:
    """Единый стиль для всех графиков: прозрачный фон, аккуратные отступы."""
    base = template
    if base is None:
        base = "plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"
    if base == "plotly_dark":
        paper_bg = "#0e1117"
        plot_bg = "#0e1117"
    else:
        paper_bg = "rgba(0,0,0,0)"
        plot_bg = "rgba(0,0,0,0)"
    fig.update_layout(
        template=base,
        paper_bgcolor=paper_bg,
        plot_bgcolor=plot_bg,
        margin=dict(l=10, r=10, t=48, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        colorway=PALETTE,
        hovermode="x unified",
    )
    return fig


def kpi_row(items: list[tuple[str, str, str | None]]) -> None:
    """Отрисовать ряд KPI-плиток: список ``(заголовок, значение, подпись)``."""
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items, strict=False):
        col.metric(label, value, help=help_text)


def page_config(title: str) -> None:
    """Стандартная конфигурация страницы дашборда."""
    st.set_page_config(page_title=f"Аналитическая платформа — {title}", layout="wide")


def require_warehouse() -> bool:
    """Показать подсказку, если данные ещё не собраны. Возвращает готовность."""
    if warehouse_exists():
        return True
    st.warning(
        "Витрины не найдены. Сначала соберите данные командой "
        "`make all` (или `make generate-data && make build && make metrics`)."
    )
    return False


def fmt_int(x: float) -> str:
    """Целое с разделителями тысяч."""
    return f"{int(round(x)):,}".replace(",", " ")


def fmt_money(x: float) -> str:
    """Денежный формат в рублях."""
    return f"{x:,.0f} ₽".replace(",", " ")


def fmt_pct(x: float) -> str:
    """Проценты с одним знаком."""
    return f"{x * 100:.1f}%"
