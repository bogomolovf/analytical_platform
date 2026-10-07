# METRICS.md — определения продуктовых метрик

Документ описывает, **как именно** считается каждая метрика в проекте: источник
данных (витрина/таблица), формула и нюансы. Все метрики материализуются слоем
`src/metrics/metrics.py` в таблицы с префиксом `metric_*` поверх витрин `marts`.

Референсная дата «сейчас» (`analysis_end`) = конец окна генерации
(`generator.end_date` в конфиге). «Текущие» значения (current MRR, North Star)
берутся на эту дату, чтобы не искажаться разреженным хвостом поздних служебных
событий.

---

## Активная аудитория

### DAU — Daily Active Users
Число уникальных пользователей, совершивших хотя бы одно **продуктовое** событие
за календарный день. Служебные события `purchase` и `churn` из активности
исключаются.
`DAU(d) = count(distinct user_id where event_date = d)`
Источник: `fct_events` → `metric_active_users.dau`.

### WAU — Weekly Active Users
Уникальные активные пользователи за скользящее окно 7 дней `[d-6; d]`.
`WAU(d) = count(distinct user_id where event_date in [d-6, d])`
Источник: `metric_active_users.wau`. Используется как **North Star** метрика.

### MAU — Monthly Active Users
Уникальные активные пользователи за скользящее окно 28 дней `[d-27; d]`.
`MAU(d) = count(distinct user_id where event_date in [d-27, d])`
Источник: `metric_active_users.mau`.

### Stickiness (DAU/MAU)
Доля месячной аудитории, которая активна в конкретный день — прокси «липкости»
продукта. Значения 10–20% типичны для SaaS.
`stickiness(d) = DAU(d) / MAU(d)`
Источник: `metric_active_users.stickiness`.

---

## Удержание (Retention)

### Day-N retention
Доля пользователей, вернувшихся в продукт **на N-й день** после регистрации,
среди тех, кто «дожил» до этого дня (у кого `signup_date + N <= max(event_date)`).
`retention(N) = returned_on_day_N / eligible_users(N)`
N ∈ {1, 3, 7, 14, 30, 60, 90} (`metrics.retention_days`).
Источник: `metric_retention_dayn`.

### Weekly cohort retention
Когорта = неделя регистрации (`cohort_week`). Для каждой пары
(когорта, N недель с регистрации) считается доля вернувшихся:
`retention(cohort, week_N) = active_users(cohort, week_N) / cohort_size(cohort)`
Источник: витрина `cohort_retention` (и heatmap на дашборде).

---

## Отток (Churn)

### Paid churn rate
Доля платящих пользователей, отписавшихся (событие `churn`), среди всех, кто
когда-либо конвертировался в платящих.
`paid_churn_rate = churned_paid_users / converted_users`
Источник: `dim_users` (`is_churned_paid`, `is_converted`) → `metric_summary`.

---

## Монетизация

### Free → Paid conversion
Доля всех зарегистрированных пользователей, совершивших хотя бы одну покупку
(подписку).
`free_to_paid = converted_users / total_users`
Источник: `dim_users.is_converted` → `metric_summary.free_to_paid_rate`.

### MRR — Monthly Recurring Revenue
Каждая активная подписка порождает одно списание в месяц, поэтому сумма
положительных покупок за календарный месяц равна MRR этого месяца. Считается
в разрезе планов (`pro` / `enterprise`).
`MRR(month) = sum(event_value where is_purchase and event_value > 0 for month)`
Источник: `fct_events` → `metric_mrr`. «Current MRR» = MRR последнего полного
месяца окна анализа.

### ARPU — Average Revenue Per Paying User
`ARPU = revenue / paying_users` (на выбранном срезе/периоде).
Считается на дашборде (страница «Выручка и сегменты»).

---

## Воронка активации

Строго **вложенная** воронка: пользователь «дошёл» до шага k, только если
совершил все предыдущие шаги (1..k) хотя бы раз. Это гарантирует монотонно
убывающую воронку и корректную пошаговую конверсию.

Шаги (`metrics.activation_funnel`):
`signup → login → create_project → run_report → purchase`

Для каждого шага считаются:
- `users` — число дошедших пользователей;
- `conv_from_prev` — конверсия относительно предыдущего шага;
- `conv_from_top` — конверсия относительно вершины (signup).

Источник: `fct_events` → `metric_activation_funnel`.

---

## Разбивки по сегментам

Единая «длинная» таблица по трём измерениям — канал привлечения, план, гео.
Для каждого значения сегмента:
- `users`, `converted_users`, `paying_users`;
- `conversion_rate = converted_users / users`;
- `revenue = sum(lifetime_revenue)`.

Источник: `dim_users` → `metric_segments`.

---

## Headline-свод (`metric_summary`)

Единая строка ключевых показателей для страницы «Обзор»:

| Поле | Смысл |
|------|-------|
| `total_users` | всего зарегистрированных пользователей |
| `converted_users` / `paying_users` | сконвертировавшиеся / активно платящие |
| `free_to_paid_rate` | конверсия free→paid |
| `paid_churn_rate` | отток платящих |
| `total_revenue` | суммарная выручка за всё окно |
| `current_mrr` | MRR последнего полного месяца |
| `north_star_wau` | WAU на референсную дату (North Star) |
| `latest_stickiness` | stickiness на референсную дату |
| `avg_dau` / `avg_mau` | средние DAU/MAU за окно |
