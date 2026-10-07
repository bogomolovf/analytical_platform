"""Тесты загрузки конфигурации."""

from __future__ import annotations

from src.config import load_config


def test_load_default_config() -> None:
    """Дефолтный конфиг читается и содержит ключевые секции."""
    cfg = load_config()
    assert isinstance(cfg.seed, int)
    assert cfg.generator["start_date"] < cfg.generator["end_date"]
    assert set(cfg.pipeline["layers"]) >= {"staging", "marts"}
    assert cfg.metrics["activation_funnel"][0] == "signup"


def test_paths_are_absolute() -> None:
    """Пути к данным резолвятся в абсолютные."""
    cfg = load_config()
    assert cfg.raw_dir.is_absolute()
    assert cfg.warehouse_path.is_absolute()


def test_get_helper() -> None:
    """Хелпер ``get`` достаёт вложенные значения и отдаёт default."""
    cfg = load_config()
    assert cfg.get("project", "seed") == cfg.seed
    assert cfg.get("nonexistent", "key", default="x") == "x"
