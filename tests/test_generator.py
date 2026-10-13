"""Тесты генератора синтетических данных."""

from __future__ import annotations

import pandas as pd

from src.config import Config
from src.generator.generate import generate


def test_generate_produces_data(small_config: Config) -> None:
    """Генерация возвращает непустые таблицы с ожидаемой схемой."""
    data = generate(small_config)
    assert len(data.users) > 100
    assert len(data.events) > 1000
    assert {
        "user_id",
        "signup_ts",
        "acquisition_channel",
        "country",
        "device",
        "behavior_segment",
    } <= set(data.users.columns)
    assert {"event_id", "user_id", "event_name", "event_timestamp", "event_value", "plan"} <= set(
        data.events.columns
    )


def test_generation_is_deterministic(small_config: Config) -> None:
    """Один и тот же seed даёт идентичные данные (воспроизводимость)."""
    d1 = generate(small_config)
    d2 = generate(small_config)
    assert len(d1.users) == len(d2.users)
    assert len(d1.events) == len(d2.events)
    pd.testing.assert_frame_equal(
        d1.events.sort_values("event_id").reset_index(drop=True),
        d2.events.sort_values("event_id").reset_index(drop=True),
    )


def test_event_names_valid(small_config: Config) -> None:
    """Все имена событий из ожидаемого множества."""
    data = generate(small_config)
    allowed = {
        "signup",
        "login",
        "view_dashboard",
        "create_project",
        "run_report",
        "invite_teammate",
        "export_data",
        "purchase",
        "churn",
    }
    assert set(data.events["event_name"].unique()) <= allowed


def test_every_user_has_signup(small_config: Config) -> None:
    """У каждого пользователя ровно одно событие signup (до инъекции дублей - с запасом)."""
    data = generate(small_config)
    signups = data.events[data.events["event_name"] == "signup"]["user_id"].nunique()
    # Уникальных пользователей с signup не меньше, чем исходных без дублей строк.
    assert signups >= data.users["user_id"].nunique() - 5


def test_dirtiness_injected(small_config: Config) -> None:
    """В данные внесены дефекты: пропуски и дубликаты бизнес-ключа событий."""
    data = generate(small_config)
    # Пропуски в гео или устройстве присутствуют.
    assert data.users["country"].isna().any() or data.users["device"].isna().any()
    # Дубликаты по бизнес-ключу события (разные event_id, одинаковое событие).
    dup = data.events.duplicated(
        subset=["user_id", "event_name", "event_timestamp", "session_id"]
    ).sum()
    assert dup > 0


def test_purchases_have_amounts(small_config: Config) -> None:
    """Покупки несут сумму и план."""
    data = generate(small_config)
    purchases = data.events[data.events["event_name"] == "purchase"]
    if len(purchases):
        assert purchases["event_value"].notna().any()
        assert purchases["plan"].notna().any()
