# Visualization Plan — CMP Ensemble HM

> Доку читает следующий Claude Code как ТЗ для всех визуализаций проекта.
> Каждая фигура самодостаточна: указан путь к источнику, тип графика, оси,
> цветовая палитра, библиотека, acceptance-проверка. Сгруппировано по тиру:
> Tier A — фигуры манускрипта (PDF vector + PNG 300 dpi), Tier B — диагностика
> в HTML-отчёте (`outputs/qc/qc_report.html`, `outputs/report.html`),
> Tier C — интерактивные исследовательские плоты.

---

## 0. Общие правила

- **Библиотеки**: matplotlib (vector PDF) для всего, что идёт в статью; seaborn — для статистических плотов поверх matplotlib; plotly — только для интерактива в HTML-отчётах.
- **Цветовая палитра** (придерживаться единой):
  - кластер 0 → `#1f77b4` (синий)
  - кластер 1 → `#ff7f0e` (оранжевый)
  - кластер 2 → `#2ca02c` (зелёный)
  - prior → серый `#7f7f7f`
  - posterior → красный `#d62728`
  - setup1 → `#1f77b4`, setup2 → `#ff7f0e`, setup3 → `#2ca02c`
  - P10/P90 envelope → полупрозрачная заливка (`alpha=0.25`)
  - P50 → сплошная линия
- **Шрифт**: matplotlib default `DejaVu Sans`, размер 10pt для подписей, 12pt для заголовков, 9pt для legend.
- **Сохранение**: каждая фигура пишется и в `outputs/figures/<id>.png` (dpi=300), и в `outputs/figures/<id>.pdf`, и копируется в `outputs/article_assets/figures_v2/<id>.{png,pdf}`.
- **Sidecar**: каждая фигура имеет `outputs/figures/<id>.png.meta.yaml` с git SHA, источниками данных, seed.
- **Запрещено**: рисовать `coverage`, `CRPS`, `cumulative_error` или любые сравнения с "правдой" — для этого датасета d_truth отсутствует (см. ТЗ §0 ревизия v2). Любая фигура, подразумевающая truth-метрику, требует sign-off пользователя.
- **Подписи на русском или английском** — единообразно. По умолчанию — английский для манускрипта (целевой Q1 журнал), русский для QC-отчёта.

---

## Tier A — Фигуры манускрипта (5 штук)

### A1. `fig01_pipeline` — Схема пайплайна

- **Роль в статье**: вводная картинка в Methods. Один взгляд → понятна последовательность.
- **Источник данных**: нет данных, чисто иллюстрация.
- **Тип**: блок-схема, matplotlib + `matplotlib.patches.FancyBboxPatch`.
- **Содержание**:
  - 4 блока слева направо: Phase 0 (Data Prep), Phase 1 (ES + QC), Phase 2 (Selection + Proxy), Phase 3 (Ablation).
  - Стрелки между блоками с подписями: "θ_prior, d_sim, d_obs", "θ_post, K, locmask", "ranking + proxy", "3 setups → metrics".
  - Внизу под каждым блоком — ключевые артефакты (`theta_prior.npy`, `mahalanobis_ranking.csv`, и т.д.).
- **Размер**: 12 × 4 дюйма, landscape.
- **Acceptance**: файл существует, открывается в Adobe Reader без ошибок, все 4 блока читаются на 100% zoom.

### A2. `fig02_qc_spread` — Spread retention по 9 θ-параметрам

- **Роль в статье**: показывает, какие параметры реально обновились, а какие нет (диагностика жёсткой локализации).
- **Источник**: `outputs/qc/spread_retention.csv` (колонки: parameter, std_prior, std_post, ratio).
- **Тип**: горизонтальный bar chart, 9 баров (по числу параметров).
- **Оси**:
  - x: std_post / std_prior, диапазон [0, 1.5], вертикальная линия на 1.0 (нет изменения).
  - y: имена параметров в порядке возрастания ratio (наиболее обновлённые сверху).
- **Цвет**: бар синий если ratio < 0.9 (сужение), серый если 0.9–1.1 (без изменения), красный если > 1.1 (расширение, тревога).
- **Аннотация**: справа от каждого бара — числовое значение ratio (3 знака).
- **Подпись**: "Posterior spread retention by parameter. Values < 1 indicate the ES update tightened the prior; values ≈ 1 mean the parameter was not updated (localization zeroed its Kalman gain row)."
- **Acceptance**: 9 баров присутствуют; AZIMUTH и THICK — синие (ratio ~0.5); MAJ_R, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP — серые (ratio ≈ 1.0).

### A3. `fig03_ablation_p10p90` — DONE, но переделать под единый стиль

- **Статус**: уже есть `outputs/figures/fig03_ablation_p10p90.{png,pdf}`. Проверить, что соответствует палитре §0; если нет — перегенерировать.
- **Роль в статье**: главная фигура раздела Results.
- **Источник**: `outputs/forecast/setup{1,2,3}_*_field_total_quantiles.csv`.
- **Тип**: 3 × 3 grid (rows = phases [oil, water, gas], cols = setups [setup1, setup2, setup3]) ИЛИ 1 × 3 grid с тремя setup'ами наложенными — выбрать второе, оно лучше передаёт ablation message.
- **Финальная компоновка**: 1 строка × 3 колонки (по фазе). В каждой панели — три setup'а оверлеем: P50 сплошная линия + P10–P90 заливка `alpha=0.25`.
- **Оси x**: время (2019–2024).
- **Оси y**: накопленная добыча, единицы из файла.
- **Legend**: единый внизу, "setup1 — baseline", "setup2 — ES + localization", "setup3 — full (≡ setup2 here)".
- **Аннотация**: на каждой панели в верхнем углу — width_ratio (setup2/setup1) из `metrics_summary.csv`.
- **Acceptance**: 3 панели, 3 кривые × 3 envelope в каждой, легенда читается; width_ratio annotation присутствует.

### A4. `fig04_cumulative_scatter` — DONE, проверить и зачистить

- **Статус**: уже есть `outputs/figures/fig04_cumulative_scatter.{png,pdf}`. Проверить осмысленность без truth.
- **Роль в статье**: показывает, как распределена итоговая добыча между моделями ансамбля.
- **Источник**: `outputs/cache/forecast.h5` (`d_forecast_cum`).
- **Тип**: 3 × 1 column subplot (по фазе). На каждой панели — scatter точек, x = setup1 cumulative-at-end, y = setup2 cumulative-at-end (по 123/149 моделям, индексируем по `cluster_ids`).
- **Цвет**: по кластеру (см. §0).
- **Диагональ**: пунктирная линия y=x; точка выше = setup2 предсказывает больше.
- **Аннотация**: median shift из `metrics_summary.csv` (текст в верхнем углу).
- **Подпись**: "Cumulative production at horizon end: setup1 (baseline) vs setup2 (ES + localization), per model. Points above the diagonal: setup2 increases predicted production for that model. Colors by cluster."
- **Acceptance**: 3 панели, ≥ 100 точек в каждой, разные цвета по кластерам, диагональ присутствует.

### A5. `fig06_cluster3_migration` — статическая matplotlib-версия

- **Роль в статье**: показывает, как сместились центроиды кластеров в θ-пространстве после ES (ключевой результат для cluster-3 "съезд" обсуждения).
- **Источник**: `outputs/qc/cluster_migration.csv` (колонки: cluster_id, parameter, reference, prior_mean, post_mean).
- **Тип**: 3 × 3 grid (rows = clusters 0/1/2, cols = первые 3 параметра по абсолютному смещению — обычно AZIMUTH, THICK, NUMBER_CHANNELS).
- **В каждой панели**: 3 вертикальные линии (reference серая, prior синяя, post красная) на числовой оси параметра.
- **Альтернатива (предпочтительнее)**: один большой grid 3 × 9, где columns — все 9 параметров, rows — все 3 кластера. Каждая ячейка показывает Δ = post − prior нормированное на σ_prior, как стрелочку от 0 до значения. Цвет стрелочки: красный если |Δ| > 1σ.
- **Оси**: x = σ-units shift, y = parameter name.
- **Acceptance**: AZIMUTH стрелочки видны (~+2.5σ во всех 3 кластерах); THICK стрелочки видны (~−1σ во всех 3); остальные 6 параметров — стрелочки нулевые (показывают факт "localization обнулил эти параметры").

---

## Tier B — Диагностические фигуры (для HTML QC-отчёта)

Не идут в статью, но обязательны в `outputs/qc/qc_report.html` и `outputs/report.html`. Pieces можно делать matplotlib PNG и встраивать через `<img>` теги, или plotly inline.

### B1. `qc_singular_spectrum` — Спектр сингулярных чисел Dp/√(N-1)

- **Источник**: `outputs/matrices/singular_values.npy` (длина 149).
- **Тип**: matplotlib log-scale line plot.
- **Оси**: x = индекс компоненты (1..149), y = singular value (log scale).
- **Аннотация**: вертикальная пунктирная линия на индексе truncation (16); горизонтальная заливка показывает "хвост" обнулённых компонент. Текст: "Kept 16/149 components, energy 0.9916".
- **Зачем**: показать, что обрезка SVD не выкидывает значимую энергию.

### B2. `qc_locmask_heatmap` — Карта локализации K

- **Источник**: `outputs/matrices/locmask.npy` (9 × 384).
- **Тип**: matplotlib imshow, binary cmap.
- **Оси**: x = индекс наблюдения d_j (с группировкой по метрике), y = θ-параметр.
- **Цвет**: чёрный = маска применена (Kalman gain зануляется), белый = маска не применена (gain пропускается).
- **Аннотация**: вертикальные разделители между блоками метрик (Накопл. нефть / вода / газ); сверху подпись `kept 60/3456 entries (1.74%)`.
- **Зачем**: показать, **почему** 6 из 9 параметров не двигаются — у них целая строка маски обнулена.

### B3. `qc_mahalanobis_distribution` — Гистограмма ||Δθ||_M по моделям

- **Источник**: `outputs/qc/mahalanobis_migration.csv` (или `outputs/selection/mahalanobis_ranking.csv`).
- **Тип**: histogram + KDE overlay, 30 bins.
- **Оси**: x = Mahalanobis distance, y = count.
- **Цвет**: 3 кластера наложены полупрозрачно (alpha=0.4) каждый своим цветом + общая огибающая чёрной линией.
- **Аннотация**: вертикальная пунктирная линия на медиане; текст с bimodality coefficient (0.368) и интерпретацией.

### B4. `qc_per_well_misfit_heatmap` — Тепловая карта misfit до/после ES

- **Источник**: `outputs/qc/per_well_misfit.csv`.
- **Тип**: 2 × 1 subplot, каждый — heatmap (16 wells × 3 metrics).
- **Цвет**: diverging cmap `RdBu_r`, центр 0, симметричный диапазон.
- **Слева**: prior misfit. Справа: posterior misfit. Annotations: значения в ячейках, если |misfit| > threshold.
- **Зачем**: визуально подтвердить, что ES уменьшил ошибку (или нет) на каких скважинах.

### B5. `qc_theta_pairgrid` — Pairplot 9 θ-параметров prior vs posterior

- **Источник**: `outputs/matrices/theta_prior.npy`, `outputs/matrices/theta_post.npy`.
- **Тип**: seaborn `PairGrid`, lower triangle = scatter (prior серый, post красный, alpha=0.4), diagonal = KDE prior + post оверлей.
- **Оси**: по 9 параметрам.
- **Зачем**: одной картинкой показать форму всего распределения, перекосы, корреляции, мультимодальность.
- **Размер**: 12 × 12 дюймов, упакованный layout.

### B6. `qc_proxy_validation_scatter` — Predicted vs actual для proxy

- **Источник**: `outputs/selection/proxy_validation_per_member.csv` + `outputs/cache/forecast.h5`.
- **Тип**: 3 × 1 panel (по кластеру), scatter predicted (от proxy на leave-one-out) vs actual (tNavigator forecast); диагональ y=x.
- **Цвет**: по фазе (oil/water/gas разными маркерами).
- **Аннотация**: median relative error per cluster (из `proxy_validation_per_cluster.csv`).
- **Зачем**: показать визуально, что proxy работает (median rel err 0.60).

### B7. `qc_forecast_per_well` — Small multiples 16 скважин

- **Источник**: `outputs/cache/forecast.h5`, ключи `d_forecast_rates` + `rate_index`.
- **Тип**: 4 × 4 grid, по одной панели на скважину. В каждой панели — нефть-rate во времени 2019–2024, 3 кривые (setup1/2/3 P50) + envelope P10–P90.
- **Размер**: 16 × 16 дюймов, размер можно сократить по факту.
- **Зачем**: детальная визуальная проверка по скважинам, какие из них setup'ы трактуют по-разному.
- **Альтернатива**: 16 PNG отдельными файлами, в HTML — карусель.

### B8. `qc_history_match_quality` — Сравнение d_sim vs d_obs (фаза истории)

- **Источник**: `outputs/matrices/d_sim_rates.npy`, `outputs/matrices/d_obs_rates.npy`, индексы из конфигов.
- **Тип**: 3 × 1 panel (по фазе oil/water/gas), field-total monthly, 2011–2018. Серое облако — все 149 моделей; черная линия — d_obs.
- **Зачем**: показать, как ансамбль покрывал историю (это уже до ES) — чтобы было видно, что прогнозный разброс не появляется на пустом месте.

---

## Tier C — Интерактивные плоты (Plotly, в HTML)

### C1. `interactive_cluster_migration` — уже существует

- Файл: `outputs/qc/cluster3_diagnostic.html`.
- Что есть: 3 subplots (по кластеру), bar chart для 9 параметров: reference / prior / post.
- Что добавить: tooltip с σ-shift, кнопка "normalize to σ_prior".

### C2. `interactive_ablation` — explorer 3 setup'ов

- Источник: `outputs/forecast/setup{1,2,3}_*_field_total_quantiles.csv`.
- Тип: plotly figure с dropdown (метрика: oil/water/gas) и легендой по setup'ам. P50 + P10/P90 заливка.
- Расположение: встроить в `outputs/report.html` как один из ключевых разделов.

### C3. `interactive_theta_explorer`

- Источник: `theta_prior.npy`, `theta_post.npy`.
- Тип: plotly scatter matrix или parallel coordinates plot, 9 параметров, цвет по кластеру, два snapshot'а prior/post.

---

## Структура HTML-отчётов

### `outputs/qc/qc_report.html` (для Phase 1 sign-off)

Разделы (jinja2 template):

1. **Header**: timestamp, git SHA, dataset summary (N=149, n_θ=9).
2. **Spread retention** → встраивает `fig02_qc_spread.png` + таблицу.
3. **Localization mask** → встраивает `qc_locmask_heatmap.png` + ratio kept.
4. **Subspace truncation** → встраивает `qc_singular_spectrum.png` + energy_kept.
5. **Mahalanobis migration** → `qc_mahalanobis_distribution.png` + BC value.
6. **Cluster centroid shift** → встраивает `fig06_cluster3_migration.png` + `cluster_migration.csv` таблицу.
7. **History match quality** → `qc_history_match_quality.png` + summary RMSE prior/post.
8. **Per-well misfit** → `qc_per_well_misfit_heatmap.png`.
9. **Pairplot** → `qc_theta_pairgrid.png` (lazy-load, тяжёлая).
10. **Physical bounds violations** → таблица из `outputs/qc/physical_bounds_violations.csv`.
11. **Verdict** строка: PASS / WARN / FAIL.

### `outputs/report.html` (финальный отчёт всего проекта)

Разделы:

1. Project summary + evaluation_mode (`forecast_no_truth_ensemble_comparison`).
2. **Pipeline diagram** (`fig01_pipeline.png`).
3. **Phase 1**: ссылка на `qc_report.html` + три ключевых KPI (collapse=0, blowup=0, rank=9).
4. **Phase 2**: топ-10 моделей из `mahalanobis_ranking.csv`, proxy validation сводка, ссылка на `qc_proxy_validation_scatter.png`.
5. **Phase 3**:
   - Главные фигуры: `fig03_ablation_p10p90.png`, `fig04_cumulative_scatter.png`, `fig06_cluster3_migration.png`.
   - Ablation table из `metrics_summary.csv`.
   - Interactive plot `interactive_ablation` встроен.
   - **Параграф про честность**: текстовая врезка, что d_truth отсутствует, поэтому метрики coverage/CRPS не приводятся.
6. **Per-well dive** (lazy): `qc_forecast_per_well.png` или 16 индивидуальных PNG.
7. **Article assets**: ссылки на `outputs/article_assets/figures_v2/` и `ablation_table.tex`.
8. **Reproducibility**: git SHA, config hash, версии библиотек.

---

## Какие фигуры в каком тире у нас УЖЕ есть

| Фигура | Тир | Статус | Файл |
|---|---|---|---|
| fig01_pipeline | A | TODO | — |
| fig02_qc_spread | A | TODO | data в `outputs/qc/spread_retention.csv` |
| fig03_ablation_p10p90 | A | partial | `outputs/figures/fig03_ablation_p10p90.{png,pdf}` (перепроверить стиль) |
| fig04_cumulative_scatter | A | partial | `outputs/figures/fig04_cumulative_scatter.{png,pdf}` |
| fig06_cluster3_migration | A | TODO (PNG) | data в `outputs/qc/cluster_migration.csv` |
| qc_singular_spectrum | B | TODO | data в `outputs/matrices/singular_values.npy` |
| qc_locmask_heatmap | B | TODO | data в `outputs/matrices/locmask.npy` |
| qc_mahalanobis_distribution | B | TODO | data в `outputs/qc/mahalanobis_migration.csv` |
| qc_per_well_misfit_heatmap | B | TODO | data в `outputs/qc/per_well_misfit.csv` |
| qc_theta_pairgrid | B | TODO | data в `outputs/matrices/theta_{prior,post}.npy` |
| qc_proxy_validation_scatter | B | TODO | data в `outputs/selection/proxy_validation_*.csv` |
| qc_forecast_per_well | B | TODO | data в `outputs/cache/forecast.h5` |
| qc_history_match_quality | B | TODO | data в `outputs/matrices/d_{sim,obs}_rates.npy` |
| interactive_cluster_migration | C | DONE | `outputs/qc/cluster3_diagnostic.html` |
| interactive_ablation | C | TODO | data в `outputs/forecast/setup*_*_quantiles.csv` |
| interactive_theta_explorer | C | TODO | data в `outputs/matrices/theta_*.npy` |

---

## Последовательность работ для Claude Code

Группа 1 (unblocked, чисто рисование из готовых CSV/NPY):

1. A2 `fig02_qc_spread` — ~30 мин.
2. A5 `fig06_cluster3_migration` (статическая) — ~45 мин.
3. B1 `qc_singular_spectrum` — ~20 мин.
4. B2 `qc_locmask_heatmap` — ~30 мин.
5. B3 `qc_mahalanobis_distribution` — ~30 мин.
6. B4 `qc_per_well_misfit_heatmap` — ~40 мин.

Группа 2 (требует чтения forecast.h5):

7. B6 `qc_proxy_validation_scatter` — ~45 мин.
8. B7 `qc_forecast_per_well` — ~1 час.
9. B8 `qc_history_match_quality` — ~30 мин.

Группа 3 (требует тонкого вкуса):

10. A1 `fig01_pipeline` (handcrafted diagram) — ~1.5 часа.
11. B5 `qc_theta_pairgrid` (heavy seaborn) — ~45 мин.
12. A3, A4 — review + restyling — ~1 час.

Группа 4 (интерактив):

13. C2 `interactive_ablation` — ~1 час.
14. C3 `interactive_theta_explorer` — ~1 час.

Группа 5 (компоновка):

15. `outputs/qc/qc_report.html` (jinja2 template) — ~2 часа.
16. `outputs/report.html` (jinja2 template) — ~2 часа.

---

## Acceptance общий

- Все Tier A фигуры существуют в `outputs/figures/<id>.{png,pdf}` И в `outputs/article_assets/figures_v2/<id>.{png,pdf}`.
- `cmp-ensemble figures` — единая CLI-команда, перегенерирует всё за один заход (~5 мин), не падает.
- `tests/test_figures.py` — проверяет существование + ненулевой размер каждого ожидаемого файла после `cmp-ensemble figures`.
- `cmp-ensemble report` — собирает `outputs/report.html`, открывается в Chrome без 404 на ассеты.
- Каждая фигура из Tier A имеет caption draft в `docs/figure_captions.md`, готовый к копированию в манускрипт.
