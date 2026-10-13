"""Генератор синтетического событийного лога SaaS-продукта.

Это ядро проекта. Модуль имитирует ~12 месяцев жизни продукта и выгружает
две «сырые» таблицы (как экспорт из событийного трекера):

* ``raw_users.csv``  - пользователи с атрибутами привлечения;
* ``raw_events.csv`` - событийный лог (signup / login / feature / purchase / churn).

Что моделируется:

* Приток регистраций с трендом роста, недельной и годовой сезонностью и
  маркетинговыми всплесками (Black Friday и т.п.).
* Поведенческие сегменты (power / casual / one_shot) со своей вероятностью
  удержания и конверсии в платящих.
* Затухающее удержание: вероятность вернуться падает по экспоненте с момента
  регистрации (halflife зависит от сегмента).
* Сессии: login + последовательность feature-событий с корректными
  таймстемпами внутри сессии.
* Монетизация: конверсия free->paid, помесячные списания (MRR) и отток
  платящих (subscription churn).
* Специально заложенная «грязь»: дубликаты, пропуски, будущие таймстемпы,
  аномальные суммы, боты-выбросы - чтобы шаг очистки в пайплайне имел смысл.

Всё детерминировано относительно ``seed`` из конфига.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import Config, load_config

# Порядковые «строительные» константы события.
_SECONDS_PER_DAY = 86_400


@dataclass
class GeneratedData:
    """Результат генерации: две связанные таблицы."""

    users: pd.DataFrame
    events: pd.DataFrame


# --------------------------------------------------------------------------- #
# 1. Кривая привлечения новых пользователей
# --------------------------------------------------------------------------- #
def _signup_curve(dates: pd.DatetimeIndex, gen: dict) -> np.ndarray:
    """Ожидаемое число регистраций по дням.

    Совмещает линейно-экспоненциальный тренд роста, недельную сезонность
    (будни > выходные), годовую сезонность и маркетинговые всплески.

    Args:
        dates: Индекс дат горизонта симуляции.
        gen: Секция ``generator`` конфига.

    Returns:
        Массив ожидаемых (лямбда для Пуассона) регистраций по каждому дню.
    """
    n_days = len(dates)
    t = np.arange(n_days)

    # Тренд роста: за год увеличиваемся в yearly_growth раз (экспонента).
    growth = gen["yearly_growth"] ** (t / 365.0)

    # Недельная сезонность: понедельник-четверг выше, выходные ниже.
    dow = dates.dayofweek.to_numpy()  # 0=Mon .. 6=Sun
    weekly = 1.0 + gen["weekly_seasonality"] * np.where(dow < 5, 0.5, -1.0)

    # Годовая сезонность: спад летом (июнь-август), пик осенью/зимой.
    doy = dates.dayofyear.to_numpy()
    yearly = 1.0 + gen["yearly_seasonality"] * np.cos(2 * np.pi * (doy - 330) / 365.0)

    lam = gen["base_daily_signups"] * growth * weekly * yearly

    # Маркетинговые всплески: временный множитель на ~5 дней вокруг даты.
    for spike in gen.get("marketing_spikes", []):
        spike_date = pd.Timestamp(spike["date"])
        offset = (dates - spike_date).days
        window = np.exp(-((offset / 2.5) ** 2))  # гауссово окно ~5 дней
        lam = lam * (1.0 + (spike["multiplier"] - 1.0) * window)

    return np.clip(lam, 0.5, None)


def _weighted_choice(rng: np.random.Generator, mapping: dict, size: int) -> np.ndarray:
    """Векторный выбор категории по словарю ``{значение: вес}``."""
    keys = list(mapping.keys())
    probs = np.array(list(mapping.values()), dtype=float)
    probs = probs / probs.sum()
    return rng.choice(keys, size=size, p=probs)


# --------------------------------------------------------------------------- #
# 2. Пользователи и их атрибуты
# --------------------------------------------------------------------------- #
def _build_users(rng: np.random.Generator, cfg: Config) -> pd.DataFrame:
    """Сгенерировать таблицу пользователей с датами регистрации и атрибутами."""
    gen = cfg.generator
    dates = pd.date_range(gen["start_date"], gen["end_date"], freq="D")
    lam = _signup_curve(dates, gen)

    # Фактические регистрации в день - Пуассон вокруг ожидаемого значения.
    daily_counts = rng.poisson(lam)
    total = int(daily_counts.sum())

    # Разворачиваем счётчики по дням в дату регистрации каждого пользователя.
    signup_days = np.repeat(dates.to_numpy(), daily_counts)

    # Внутридневное время: смещённое к рабочим часам (пик ~14:00).
    hour = np.clip(rng.normal(14, 4, total), 0, 23.999)
    seconds = (hour * 3600 + rng.integers(0, 3600, total)).astype("int64")
    signup_ts = pd.to_datetime(signup_days) + pd.to_timedelta(seconds, unit="s")

    behavior_map = {k: v["share"] for k, v in gen["behavior_segments"].items()}

    users = pd.DataFrame(
        {
            "user_id": [f"u_{i:07d}" for i in range(total)],
            "signup_ts": signup_ts,
            "acquisition_channel": _weighted_choice(rng, gen["channels"], total),
            "country": _weighted_choice(rng, gen["geos"], total),
            "device": _weighted_choice(rng, gen["devices"], total),
            "behavior_segment": _weighted_choice(rng, behavior_map, total),
            "initial_plan": "free",
        }
    )
    users = users.sort_values("signup_ts").reset_index(drop=True)
    return users


# --------------------------------------------------------------------------- #
# 3. Симуляция событий одного пользователя
# --------------------------------------------------------------------------- #
def _feature_arrays(gen: dict) -> tuple[list[str], np.ndarray]:
    """Список feature-событий и нормированные вероятности их выбора."""
    features = list(gen["feature_events"].keys())
    weights = np.array(list(gen["feature_events"].values()), dtype=float)
    return features, weights / weights.sum()


def _simulate_user(
    rng: np.random.Generator,
    user: dict,
    cfg: Config,
    features: list[str],
    feature_probs: np.ndarray,
    end_date: datetime,
) -> list[dict]:
    """Смоделировать полный событийный поток одного пользователя.

    Возвращает список событий (dict-ов). Логика:
    signup -> активные дни с сессиями (login + feature-события) ->
    возможная конверсия в платящего с помесячными списаниями -> отток.
    """
    gen = cfg.generator
    seg_cfg = gen["behavior_segments"][user["behavior_segment"]]
    events: list[dict] = []

    signup_ts: pd.Timestamp = user["signup_ts"]
    user_id = user["user_id"]
    lifespan_days = (end_date - signup_ts.to_pydatetime()).days
    if lifespan_days < 0:
        return events

    # --- signup + первый login в день регистрации ------------------------- #
    events.append(_mk_event(user_id, "signup", signup_ts, session_id=f"{user_id}_s0"))

    # Определяем активные дни: день 0 активен всегда, дальше - по затуханию.
    offsets = np.arange(1, lifespan_days + 1)
    halflife = seg_cfg["retention_halflife_days"]
    return_prob = seg_cfg["base_return_prob"] * 0.5 ** (offsets / halflife)
    # Выходные слегка снижают вероятность вернуться.
    day_dow = (signup_ts + pd.to_timedelta(offsets, unit="D")).dayofweek.to_numpy()
    return_prob = return_prob * np.where(day_dow < 5, 1.0, 0.7)
    active_mask = rng.random(len(offsets)) < return_prob
    active_offsets = np.concatenate(([0], offsets[active_mask]))

    smin, smax = seg_cfg["sessions_per_active_day"]
    emin, emax = seg_cfg["events_per_session"]

    session_counter = 0
    for off in active_offsets:
        day_start = signup_ts.normalize() + pd.Timedelta(days=int(off))
        n_sessions = int(rng.integers(smin, smax + 1))
        for _ in range(n_sessions):
            session_counter += 1
            session_id = f"{user_id}_s{session_counter}"
            # Старт сессии - рабочие часы с шумом.
            start_sec = int(np.clip(rng.normal(14, 4), 0, 23.9) * 3600)
            cursor = day_start + pd.Timedelta(seconds=start_sec)
            # Каждая сессия начинается с login.
            events.append(_mk_event(user_id, "login", cursor, session_id=session_id))
            n_events = int(rng.integers(emin, emax + 1))
            chosen = rng.choice(features, size=n_events, p=feature_probs)
            for feat in chosen:
                # Промежуток между действиями: 20с..6мин.
                cursor = cursor + pd.Timedelta(seconds=int(rng.integers(20, 360)))
                events.append(_mk_event(user_id, feat, cursor, session_id=session_id))

    # --- Монетизация: конверсия free->paid и помесячный MRR ---------------- #
    if rng.random() < seg_cfg["convert_prob"]:
        conv_offset = int(rng.exponential(25)) + 3
        if conv_offset <= lifespan_days:
            plan = "enterprise" if rng.random() < gen["enterprise_share_of_paid"] else "pro"
            price = gen["plans"][plan]
            cycle_date = signup_ts.normalize() + pd.Timedelta(days=conv_offset)
            # Помесячные списания, пока пользователь не оттёк.
            while cycle_date.to_pydatetime() <= end_date:
                ts = cycle_date + pd.Timedelta(seconds=int(rng.integers(0, _SECONDS_PER_DAY)))
                events.append(
                    _mk_event(
                        user_id,
                        "purchase",
                        ts,
                        session_id=f"{user_id}_pay",
                        event_value=float(price),
                        plan=plan,
                    )
                )
                # Проверка оттока по итогам месяца.
                if rng.random() < gen["monthly_paid_churn"]:
                    churn_ts = ts + pd.Timedelta(days=int(rng.integers(1, 25)))
                    if churn_ts.to_pydatetime() <= end_date:
                        events.append(
                            _mk_event(
                                user_id, "churn", churn_ts, session_id=f"{user_id}_pay", plan=plan
                            )
                        )
                    break
                cycle_date = cycle_date + pd.Timedelta(days=30)

    return events


def _mk_event(
    user_id: str,
    name: str,
    ts: pd.Timestamp,
    session_id: str | None = None,
    event_value: float | None = None,
    plan: str | None = None,
) -> dict:
    """Собрать словарь одного события (event_id проставляется позже, глобально)."""
    return {
        "user_id": user_id,
        "session_id": session_id,
        "event_name": name,
        "event_timestamp": ts,
        "event_value": event_value,
        "plan": plan,
    }


# --------------------------------------------------------------------------- #
# 4. Инъекция «грязи»
# --------------------------------------------------------------------------- #
def _inject_dirt(
    rng: np.random.Generator,
    users: pd.DataFrame,
    events: pd.DataFrame,
    cfg: Config,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Добавить реалистичные дефекты данных (для осмысленной очистки в staging)."""
    d = cfg.generator["dirtiness"]
    end_ts = pd.Timestamp(cfg.generator["end_date"]) + pd.Timedelta(days=1)

    # 4.1 Пропуски в гео/устройстве.
    geo_null = rng.random(len(users)) < d["null_geo_rate"]
    dev_null = rng.random(len(users)) < d["null_device_rate"]
    users.loc[geo_null, "country"] = None
    users.loc[dev_null, "device"] = None

    # 4.2 Дубликаты строк пользователей.
    n_dup_users = int(len(users) * d["duplicate_user_rate"])
    if n_dup_users:
        dup_users = users.sample(n_dup_users, random_state=int(rng.integers(1e9)))
        users = pd.concat([users, dup_users], ignore_index=True)

    # 4.3 Боты-выбросы: несколько пользователей с аномально большим числом событий.
    bot_rows = []
    bot_ids = users["user_id"].sample(d["bot_outlier_users"], random_state=int(rng.integers(1e9)))
    for bot_id in bot_ids:
        base_ts = pd.Timestamp(cfg.generator["start_date"]) + pd.Timedelta(
            days=int(rng.integers(0, 300))
        )
        n = int(rng.integers(3000, 6000))
        secs = np.cumsum(rng.integers(1, 5, n))
        for s in secs:
            bot_rows.append(
                _mk_event(
                    bot_id,
                    "view_dashboard",
                    base_ts + pd.Timedelta(seconds=int(s)),
                    session_id=f"{bot_id}_bot",
                )
            )
    if bot_rows:
        events = pd.concat([events, pd.DataFrame(bot_rows)], ignore_index=True)

    # 4.4 Дубликаты событий.
    n_dup_ev = int(len(events) * d["duplicate_event_rate"])
    if n_dup_ev:
        dup_ev = events.sample(n_dup_ev, random_state=int(rng.integers(1e9)))
        events = pd.concat([events, dup_ev], ignore_index=True)

    # 4.5 Редкие «события из будущего».
    fut = rng.random(len(events)) < d["future_timestamp_rate"]
    events.loc[fut, "event_timestamp"] = end_ts + pd.to_timedelta(
        rng.integers(1, 400, fut.sum()), unit="D"
    )

    # 4.6 Аномальные (отрицательные) суммы покупок.
    purchase_idx = events.index[events["event_name"] == "purchase"]
    if len(purchase_idx):
        neg = rng.random(len(purchase_idx)) < d["negative_amount_rate"]
        bad_idx = purchase_idx[neg]
        events.loc[bad_idx, "event_value"] = -events.loc[bad_idx, "event_value"].abs()

    # Перемешиваем события и присваиваем глобальные event_id (с дублями внутри - ок,
    # они снимаются в staging по бизнес-ключу).
    events = events.sample(frac=1.0, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    events.insert(0, "event_id", [f"e_{i:09d}" for i in range(len(events))])
    return users, events


# --------------------------------------------------------------------------- #
# 5. Публичная точка входа
# --------------------------------------------------------------------------- #
def generate(cfg: Config, n_users_override: int | None = None) -> GeneratedData:
    """Сгенерировать полный набор данных в памяти.

    Args:
        cfg: Конфигурация проекта.
        n_users_override: Если задано - жёстко ограничить число пользователей
            (усечь сгенерированную когорту). Удобно для быстрых тестов.

    Returns:
        :class:`GeneratedData` с таблицами ``users`` и ``events``.
    """
    rng = np.random.default_rng(cfg.seed)
    users = _build_users(rng, cfg)
    if n_users_override is not None:
        users = users.head(n_users_override).reset_index(drop=True)

    features, feature_probs = _feature_arrays(cfg.generator)
    end_date = datetime.fromisoformat(cfg.generator["end_date"]) + timedelta(days=1)

    all_events: list[dict] = []
    for user in users.to_dict("records"):
        all_events.extend(_simulate_user(rng, user, cfg, features, feature_probs, end_date))

    events = pd.DataFrame(all_events)
    users, events = _inject_dirt(rng, users, events, cfg)
    return GeneratedData(users=users, events=events)


def write_raw(data: GeneratedData, cfg: Config) -> tuple[Path, Path]:
    """Записать сгенерированные таблицы в ``data/raw`` в формате CSV.

    Returns:
        Кортеж путей ``(users_csv, events_csv)``.
    """
    raw_dir = cfg.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    users_path = raw_dir / "raw_users.csv"
    events_path = raw_dir / "raw_events.csv"
    data.users.to_csv(users_path, index=False)
    data.events.to_csv(events_path, index=False)
    return users_path, events_path


def main() -> None:
    """CLI-обёртка: генерация данных и запись в ``data/raw``."""
    parser = argparse.ArgumentParser(description="Генерация синтетических данных продукта.")
    parser.add_argument("--config", default=None, help="Путь к config.yaml")
    parser.add_argument("--users", type=int, default=None, help="Ограничить число пользователей")
    parser.add_argument("--seed", type=int, default=None, help="Переопределить random seed")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.seed is not None:
        cfg.raw["project"]["seed"] = args.seed

    print(
        f"[generate] seed={cfg.seed}, период "
        f"{cfg.generator['start_date']}..{cfg.generator['end_date']}"
    )
    data = generate(cfg, n_users_override=args.users)
    users_path, events_path = write_raw(data, cfg)
    print(
        f"[generate] пользователей: {len(data.users):,} | "
        f"событий: {len(data.events):,}\n"
        f"[generate] записано: {users_path}\n"
        f"[generate] записано: {events_path}"
    )


if __name__ == "__main__":
    main()
