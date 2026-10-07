"""Загрузка и типизация конфигурации проекта из ``config/config.yaml``.

Модуль предоставляет единую точку доступа к настройкам для генератора,
пайплайна и слоя метрик. Конфиг парсится в лёгкие ``dataclass``-обёртки,
чтобы код был типизирован и не «магически» тянул словари.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Корень репозитория = на два уровня выше этого файла (src/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@dataclass(frozen=True)
class Config:
    """Обёртка над сырым словарём конфигурации.

    Хранит распарсенный YAML и предоставляет удобные свойства с приведением
    относительных путей к абсолютным относительно корня проекта.
    """

    raw: dict[str, Any] = field(repr=False)
    root: Path = PROJECT_ROOT

    # ------------------------------------------------------------------ #
    # Базовые свойства
    # ------------------------------------------------------------------ #
    @property
    def seed(self) -> int:
        """Глобальный random seed для воспроизводимости."""
        return int(self.raw["project"]["seed"])

    @property
    def raw_dir(self) -> Path:
        """Абсолютный путь к каталогу сырых CSV-выгрузок."""
        return self.root / self.raw["paths"]["raw_dir"]

    @property
    def warehouse_path(self) -> Path:
        """Абсолютный путь к файлу БД DuckDB."""
        return self.root / self.raw["paths"]["warehouse"]

    @property
    def generator(self) -> dict[str, Any]:
        """Секция настроек генератора."""
        return self.raw["generator"]

    @property
    def pipeline(self) -> dict[str, Any]:
        """Секция настроек пайплайна."""
        return self.raw["pipeline"]

    @property
    def metrics(self) -> dict[str, Any]:
        """Секция настроек метрик."""
        return self.raw["metrics"]

    def get(self, *keys: str, default: Any = None) -> Any:
        """Безопасно достать вложенное значение по цепочке ключей."""
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


def load_config(path: str | Path | None = None) -> Config:
    """Прочитать YAML-конфиг и вернуть объект :class:`Config`.

    Args:
        path: Путь к YAML-файлу. Если ``None`` — используется путь по умолчанию
            ``config/config.yaml`` в корне репозитория.

    Returns:
        Экземпляр :class:`Config`.

    Raises:
        FileNotFoundError: если файл конфигурации не найден.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Не найден файл конфигурации: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config(raw=raw)
