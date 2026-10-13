# ============================================================================
# Makefile - единая точка входа в проект.
#   make setup          установить зависимости и pre-commit хуки
#   make generate-data  сгенерировать синтетические данные -> data/raw
#   make build          собрать витрины (raw -> staging -> marts) + DQ-тесты
#   make metrics        рассчитать слой продуктовых метрик
#   make pipeline       generate-data + build + metrics (весь ELT)
#   make test           прогнать pytest
#   make lint           ruff + black --check
#   make format         автоформат (ruff --fix + black)
#   make dashboard      поднять Streamlit-дашборд
#   make all            весь пайплайн end-to-end и запуск дашборда
#   make clean          удалить сгенерированные данные и кэши
# ============================================================================
PYTHON ?= python3

.PHONY: setup generate-data build metrics pipeline test lint format dashboard all clean

setup:
	$(PYTHON) -m pip install -r requirements.txt
	-pre-commit install

generate-data:
	$(PYTHON) -m src.generator.generate

build:
	$(PYTHON) -m src.pipeline.runner

metrics:
	$(PYTHON) -m src.metrics.metrics

pipeline: generate-data build metrics

test:
	$(PYTHON) -m pytest

lint:
	ruff check .
	black --check .

format:
	ruff check --fix .
	black .

dashboard:
	streamlit run "dashboard/Приложение.py"

# Полный прогон «одной командой»: данные -> витрины -> метрики -> дашборд.
all: pipeline dashboard

clean:
	rm -rf data/raw data/warehouse.duckdb data/warehouse.duckdb.wal
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Очищено: сгенерированные данные и кэши."
