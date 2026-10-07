# Git-коммиты и заливка на GitHub

Проект намеренно **не** инициализирует git — это делается вручную. Ниже готовый
план осмысленных коммитов по логическим этапам и пошаговая инструкция публикации.

## План коммитов (по логическим этапам)

Можно закоммитить всё сразу, но для «истории проекта» аккуратнее по этапам:

```bash
git init
git add .gitignore LICENSE pyproject.toml requirements.txt config/
git commit -m "chore: инициализация проекта, конфиг, зависимости и лицензия"

git add src/config.py src/__init__.py src/generator/
git commit -m "feat(generator): синтетический генератор событий SaaS за 12 месяцев

Пользователи с атрибутами привлечения, поведенческие сегменты, затухающее
удержание, сессии, монетизация (free→paid, MRR, churn) и инъекция грязных
данных. Полностью детерминирован seed'ом."

git add src/pipeline/ sql/staging/ sql/marts/
git commit -m "feat(pipeline): ELT на DuckDB и dbt-style SQL-модели raw→staging→marts

Мини dbt-раннер с ref()/source(), топологической сортировкой и материализацией
витрин: dim_users, dim_dates, fct_events, fct_sessions, agg_daily_activity,
cohort_retention."

git add sql/tests/
git commit -m "test(dq): data-quality тесты (uniqueness, not null, ссылочная целостность)"

git add src/metrics/ METRICS.md
git commit -m "feat(metrics): слой продуктовых метрик и их определения

DAU/WAU/MAU, stickiness, retention (day-N и когортный), churn, free→paid,
воронка активации, MRR и разбивки по сегментам. Определения — в METRICS.md."

git add dashboard/ .streamlit/
git commit -m "feat(dashboard): многостраничный Streamlit-дашборд с фильтрами и темами

Обзор (North Star + KPI), рост/активность, retention (heatmap), воронка,
выручка/сегменты. Plotly, светлая и тёмная тема."

git add tests/ .pre-commit-config.yaml .github/
git commit -m "ci: pytest, ruff/black, pre-commit и GitHub Actions"

git add notebooks/ docs/ Makefile README.md
git commit -m "docs: explanatory-ноутбук, README с архитектурой и скриншотами, Makefile"
```

## Публикация на GitHub

### Вариант A — через GitHub CLI (быстро)

```bash
gh repo create product-analytics-platform --public --source=. --remote=origin --push
```

### Вариант B — вручную

1. Создайте пустой репозиторий на GitHub (без README/лицензии, они уже есть):
   **New repository → имя `product-analytics-platform` → Create**.
2. Свяжите и запушьте:

```bash
git branch -M main
git remote add origin https://github.com/<your-username>/product-analytics-platform.git
git push -u origin main
```

### Описание репозитория (About)

> End-to-end продуктовая аналитическая платформа (мини-Amplitude): генерация
> синтетических событий → ELT на DuckDB (dbt-style модели) → слой продуктовых
> метрик → интерактивный Streamlit-дашборд. Python, DuckDB, SQL, Streamlit,
> Plotly, pytest, CI.

**Topics:** `product-analytics`, `data-engineering`, `duckdb`, `streamlit`,
`elt`, `dbt`, `python`, `sql`, `analytics`, `dashboard`, `portfolio`.

После пуша убедитесь, что во вкладке **Actions** прошёл CI (lint + tests).
Данные (`data/`) в репозиторий не попадают — они генерируются командой
`make all` на свежем клоне.
