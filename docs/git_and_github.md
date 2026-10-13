# Git и заливка на GitHub

Проект намеренно не инициализирует git, это делается вручную. Ниже готовый план осмысленных коммитов по этапам и короткая инструкция по публикации.

## План коммитов по этапам

Можно закоммитить всё сразу, но для аккуратной истории проекта лучше по этапам.

```bash
git init
git add .gitignore LICENSE pyproject.toml requirements.txt config/
git commit -m "chore: инициализация проекта, конфиг, зависимости и лицензия"

git add src/config.py src/__init__.py src/generator/
git commit -m "feat(generator): синтетический генератор событий SaaS за 12 месяцев"

git add src/pipeline/ sql/staging/ sql/marts/
git commit -m "feat(pipeline): ELT на DuckDB, модели raw, staging, marts в стиле dbt"

git add sql/tests/
git commit -m "test(dq): тесты качества данных (уникальность, not null, ссылочная целостность)"

git add src/metrics/ METRICS.md
git commit -m "feat(metrics): слой продуктовых метрик и их определения"

git add dashboard/ .streamlit/
git commit -m "feat(dashboard): многостраничный дашборд на Streamlit с фильтрами и темами"

git add tests/ .pre-commit-config.yaml .github/
git commit -m "ci: pytest, ruff, black, pre-commit и GitHub Actions"

git add notebooks/ docs/ Makefile README.md
git commit -m "docs: ноутбук с разбором данных, README и Makefile"
```

## Как опубликовать

Вариант через GitHub CLI, если он установлен.

```bash
gh repo create product-analytics-platform --public --source=. --remote=origin --push
```

Вариант вручную. Создаёте на GitHub пустой репозиторий без README и лицензии, они уже есть в проекте. Потом связываете и пушите.

```bash
git branch -M main
git remote add origin https://github.com/<ваш-логин>/product-analytics-platform.git
git push -u origin main
```

## Описание репозитория

Короткое описание для поля About на странице репозитория.

Полноценная система продуктовой аналитики на синтетических данных. События SaaS проходят через ELT на DuckDB и модели в стиле dbt, превращаются в продуктовые метрики и показываются в дашборде на Streamlit. Python, DuckDB, SQL, Streamlit, Plotly, pytest.

Темы для репозитория: product-analytics, data-engineering, duckdb, streamlit, elt, dbt, python, sql, dashboard, portfolio.

После пуша проверьте, что во вкладке Actions прошёл CI с линтерами и тестами. Данные в репозиторий не попадают, они генерируются командой make all на свежем клоне.
