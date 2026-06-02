# ТЗ для Claude Code: ансамблевый прогноз для CMP / Watt Field

> **Контекст одной строкой**: у нас 150 уже посчитанных tNavigator-моделей (3 кластера × 50). Внутри кластера все 50 моделей наследуют одинаковый θ_adapt от центроида. Нужно реализовать post-hoc ES-апдейт + ablation-блок прогноза по методологии Evensen, Oliver, Hanea (2026), чтобы получить честный посteriорный ансамбль и сравнить три варианта прогноза.

---

## 0. Журнал ревизий ТЗ (что изменилось после аудита данных)

**Ревизия v2 — 2026-06-02 (сессии 002–005 + addendum).** Изначальный ТЗ был написан под гипотетическую файловую структуру `data/ensemble_150/...`. После реального осмотра входных данных и подтверждения от пользователя зафиксированы следующие правки. Они **переопределяют** оригинальные формулировки в случае конфликта.

| Что изменилось | Было (v1) | Стало (v2) | Где |
|---|---|---|---|
| Источник данных | дерево `data/ensemble_150/...` с CSV | 4 Excel-файла в корне репо | §3 |
| Число параметров n_θ | 12 (workflow_params) | **9** (θ_adapt: THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP) | §3 |
| Размер ансамбля N | 150 | **149** (одна модель `51-1_1-173` с обрезанной таймлинией пропущена) | §3 |
| Forecast-симуляции | опционально, ожидались | **123 из 150 досчитаны** (2019-01 → 2024-10, 70 месяцев); 27 отвалились "pressure depletion" | §3 |
| Скважины | 17 продюсеров + 6 инжекторов | **16 продюсеров + 6 инжекторов** (1 продюсер из ТЗ §3 в данных отсутствует) + 1 dummy `B` фильтруется | §3 |
| workflow_params (controls) | 150 × 12 | **отсутствуют** → setup3 вырождается в setup2 с warning | §3, §6 Task 3.1 |
| d_truth (правда на forecast-период) | опционально через `truth/` | **принципиально недоступен** — реальные замеры обрываются 2018-12-13 | §3, §6 Task 3.3 |
| Train/val split (Task 3.4) | fallback при отсутствии truth | **снят с повестки** — d_truth на val-слайсе всё равно не существует, hindcast ничего не даст | §6 Task 3.4 |
| Метрики coverage / CRPS / cumulative_error | обязательны | **формально неприменимы** для этого датасета (нет d_truth). Код остаётся, активируется автоматически если truth когда-либо появится | §6 Task 3.3, §11 |
| Acceptance ablation | "coverage_2 ≥ coverage_1, CRPS_2 ≤ CRPS_1" | **сравнение ансамблей между собой** через width_ratio и median_shift; правильность не оценивается | §6 acceptance Phase 3, §11 |
| Число фигур | 6 (fig01..fig06) | **5** — fig05_crps_time retired (CRPS не считается) | §4 |
| Геологические файлы (`geology/`) | для Фазы 4 | отсутствуют — но Фаза 4 и так out of scope | §3, §12 |
| BHP в истории | плотное покрытие | **разрежено**: ~10% строк ненулевые. C_dd для BHP-слотов инфлирован до σ=1e6 | §3 |
| Линкинг моделей | model_id ↔ путь | `round(SEED)` из `models_near_adapted_centroids.xlsx` = суффикс листа в `Показатели динамики.xlsx`. Проверено 150/150 | §3 |

**Что НЕ изменилось:** методология ES + локализация + subspace SVD (Фаза 1), Mahalanobis + linear proxy (Фаза 2), три setup'а в Фазе 3 как идея, стек, CLI, дисциплина артефактов.

---

## 1. Цель и не-цель

**Цель**: реализовать Python-пайплайн, который:
1. Собирает матрицы из готовых tNavigator-выгрузок (Фаза 0)
2. Делает один ES-апдейт расширенного state vector с localization (Фаза 1)
3. Отбирает подмножество моделей для прогнозного пересчёта (Фаза 2)
4. Запускает три варианта прогноза параллельно и считает метрики (Фаза 3)
5. Генерирует графики и сводную таблицу для статьи

**Не-цель**: переобучать CNN, перегенерировать ансамбль геологий, реализовывать APS-soft-category (это отдельная Фаза 4 — пока не делаем). tNavigator-симуляции запускаются вручную пользователем по списку, который сгенерирует пайплайн.

---

## 2. Стек

- Python 3.11+
- `numpy`, `scipy`, `pandas`, `matplotlib`, `seaborn`
- `h5py` для хранения матриц
- `scikit-learn` для PCA/SVD-утилит
- `pyyaml` для конфигов
- `pytest` для тестов
- Без deep learning: CNN уже обучена, GMM-метки уже есть
- Без распределённых вычислений: всё крутится локально

---

## 3. Входные данные (реальная структура, как лежит в репо)

```
F:\СМП\Статья 2.0\Ensamble HM\
├── models_near_adapted_centroids.xlsx     # 3 листа (по кластеру) × 50 моделей
│                                            # Колонки: MODEL, SEED, и 9 θ-параметров
│                                            # (THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS,
│                                            #  CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP)
│                                            # Первая строка каждого листа —
│                                            # "Адаптированный центроид →" (reference θ)
│
├── Показатели динамики.xlsx               # 150 листов = 150 моделей tNavigator
│                                            # 97 строк (помесячно 2011-01 → 2018-12-13)
│                                            # 581 колонка: <metric> для поля + <metric> (<well>)
│                                            # Линкинг: суффикс листа = round(SEED) из θ-файла
│
├── Исторические значения.xlsx             # long-format, 2231 строки = 23 скв × 97 мес
│                                            # ~48 метрик на строку (rates / cum / BHP / injection)
│                                            # Период: 2011-01-01 → 2018-12-13
│
├── Кроссплоты.xlsx                        # 5 листов × 150 моделей × 23 скв
│                                            # End-of-history snapshot, используется как
│                                            # sanity-check для phase0 (не основной d_sim)
│
├── outputs/cache/forecast.h5              # ГОТОВЫЙ кэш forecast-симуляций
│                                            # 123 модели × 70 месяцев (2019-01 → 2024-10)
│                                            # 3 cum + 3 rate метрики × 16 продюсеров
│                                            # Источник: decoded_results.xlsx
│                                            # (сам файл в репо отсутствует — есть только кэш)
│
├── configs/                               # СГЕНЕРИРОВАНЫ при scaffold-001, НЕ внешний вход
│   ├── default.yaml                       # глобальные параметры (см. §7)
│   ├── experiment_setups.yaml             # 3 setup'а (см. §6 Task 3.1)
│   ├── theta_schema.yaml                  # 9 параметров, ranges по data envelope
│   ├── noise_spec.yaml                    # σ = 15% × |d_obs|, floor, diagonal
│   └── well_layout.yaml                   # 16 продюсеров + 6 инжекторов, типы по префиксу
│                                            # (координаты null — отсутствуют, не нужны для
│                                            # correlation-based localization)
│
└── TZ_ensemble_forecast.md                # этот документ
```

**Чего НЕТ и принципиально не появится:**

- `workflow_params.csv` (150 × 12 controls) — отсутствует. **Следствие**: setup3 (`use_control_uncertainty=true`) автоматически вырождается в setup2 с залогированным warning. Метрики setup2 и setup3 будут byte-identical.
- `data/truth/forecast_truth.csv` (реальные замеры на 2019–2024) — **отсутствует и не появится** (подтверждено пользователем в сессии 005). Реальная история обрывается 2018-12-13. **Следствие**: метрики coverage_p10p90, CRPS, cumulative_error формально неприменимы; см. §6 Task 3.3.
- `data/geology/{latents_v2.csv, gmm_k3.csv, workflow_combined.xlsx}` — отсутствуют. Эти файлы нужны только для Фазы 4, которая out of scope (§12).
- Координаты скважин — отсутствуют. Не нужны: локализация в этом проекте корреляционная, а не дистанционная.

**Контракт данных, который надо уважать:**

- Wells: 23 активных + 1 dummy `B` (нули везде, фильтруется на загрузке). 16 продюсеров (`WELL1..WELL10`, `WELL1A/1B/2A/3A/4A/5A`) + 6 инжекторов (`INJ1..INJ6`).
- Time grid истории: 2011-01-01 → 2018-12-13, 97 шагов, не строго календарные (есть day-of-month drift) — loader сохраняет реальные timestamp'ы.
- Time grid forecast: 2019-01-01 → 2024-10-01, 70 шагов.
- BHP в истории разрежён (~10% ненулевых) — C_dd для нулевых BHP-слотов инфлируется до σ=1e6, чтобы не доминировать в ES без удаления самих слотов из d_obs (длина d_obs/d_sim сохраняется).
- N=149 в Фазе 1 (одна модель битая), M=123 в Фазе 3 (только модели с готовым forecast).

**Валидация**: pydantic v2 в `src/cmp_ensemble/io/schemas.py`. Если реальный файл расходится со схемой — обновлять схему и добавлять regression-fixture, **не молча кастовать**.

---

## 4. Выходные артефакты

```
outputs/
├── matrices/
│   ├── theta_prior.npy              # 150 × n_θ
│   ├── theta_post.npy               # 150 × n_θ (после ES)
│   ├── u_prior.npy                  # 150 × n_u (controls)
│   ├── u_post.npy                   # 150 × n_u
│   ├── d_obs.npy                    # n_d
│   ├── d_sim.npy                    # 150 × n_d
│   ├── C_dd.npy                     # n_d × n_d (диагональная)
│   ├── K.npy                        # gain matrix (для аудита)
│   └── locmask.npy                  # маска локализации (n_z × n_d)
│
├── qc/
│   ├── spread_retention.csv         # std_post/std_prior по каждой компоненте
│   ├── rank_check.json              # rank(Z_post), rank(Z_prior), n_zero_singular
│   ├── mahalanobis_migration.csv    # 150 значений ||Δθ||_M
│   ├── cluster3_diagnostic.html     # отдельный отчёт по «съезду» кластера 3
│   └── qc_report.html               # сводный QC-отчёт
│
├── selection/
│   ├── models_to_resimulate.csv     # X моделей для tNavigator forecast (топ-X)
│   ├── models_proxy.csv             # 150-X моделей под прокси
│   └── proxy_validation.csv         # ошибка прокси на 10 валидационных моделях
│
├── forecast/
│   ├── setup1_naive/                # baseline (текущий подход)
│   ├── setup2_localized/            # + localization
│   ├── setup3_full/                 # + control uncertainty + cumulative
│   └── metrics_summary.csv          # сводная таблица метрик по 3 постановкам
│
├── figures/
│   ├── fig01_pipeline.png           # схема пайплайна
│   ├── fig02_qc_spread.png          # QC: spread retention
│   ├── fig03_ablation_p10p90.png    # 3 постановки × 3 кластера × фазы (аналог Fig 14.7)
│   ├── fig04_cumulative_scatter.png # scatter cumulative (аналог Fig 14.10)
│   └── fig06_cluster3_migration.png # диагностика «съезда» кластера 3
│   # fig05_crps_time.png — RETIRED (нет d_truth → CRPS не считается)
│
└── article_assets/
    ├── ablation_table.tex           # LaTeX-таблица метрик
    └── figures_v2/                  # пережатые PNG (300 dpi) и PDF (vector) для статьи
```

**Каждый артефакт** под `outputs/` обязан иметь sidecar `*.meta.yaml` с git SHA, seed, config hash, timestamp, и (для Phase 3) полем `evaluation_mode: no_truth_baseline_only` — фиксированное значение для этого проекта.

---

## 5. Структура проекта

```
cmp_ensemble/
├── pyproject.toml
├── README.md
├── configs/
│   ├── default.yaml                 # глобальные параметры пайплайна
│   └── experiment_setups.yaml       # описания 3 ablation-постановок
├── src/cmp_ensemble/
│   ├── __init__.py
│   ├── io/
│   │   ├── tnav_loader.py           # выгрузка из tNavigator
│   │   ├── observations.py          # загрузка исторических данных
│   │   └── schemas.py               # pydantic-модели для входных файлов
│   ├── ensemble/
│   │   ├── es_update.py             # ES-апдейт
│   │   ├── localization.py          # adaptive correlation-based localization
│   │   ├── state_vector.py          # сборка/распаковка z = (θ, u)
│   │   └── subspace.py              # SVD-проекция (Глава 6)
│   ├── selection/
│   │   ├── mahalanobis.py           # ||Δθ||_M
│   │   ├── linear_proxy.py          # ансамблевая чувствительность
│   │   └── compute_planner.py       # компромиссная стратегия отбора
│   ├── forecast/
│   │   ├── setups.py                # три постановки
│   │   ├── metrics.py               # CRPS, coverage, width ratio
│   │   └── aggregation.py           # P10/P50/P90 по ансамблю
│   ├── qc/
│   │   ├── checks.py                # все QC-проверки Фазы 1
│   │   └── reports.py               # HTML-отчёты
│   ├── viz/
│   │   ├── ablation.py              # аналоги Fig 14.7-14.12
│   │   └── diagnostics.py           # QC-графики
│   └── cli.py                       # точка входа: cmp-ensemble run --phase 1
├── tests/
│   ├── test_io.py
│   ├── test_es_update.py
│   ├── test_localization.py
│   ├── test_metrics.py
│   └── fixtures/                    # синтетические мини-датасеты (N=20, n_d=10)
└── notebooks/
    ├── 01_data_exploration.ipynb
    ├── 02_es_update_diagnostics.ipynb
    └── 03_forecast_ablation.ipynb
```

---

## 6. Задачи по фазам

### Фаза 0 — Подготовка данных

**Task 0.1: TNavigator loader**

```python
def load_tnav_ensemble(
    manifest_path: Path,
    schema: TNavSchema,
) -> EnsembleData:
    """
    Загружает 150 моделей из tNavigator-выгрузок.
    
    Returns:
        EnsembleData с полями:
            theta: np.ndarray (150, n_θ)
            theta_names: list[str]
            d_sim_rates: np.ndarray (150, n_d_rates)  # помесячные дебиты
            d_sim_cum: np.ndarray (150, n_d_cum)       # накопленные на конец года
            cluster_ids: np.ndarray (150,)
            model_ids: np.ndarray (150,)
            time_steps: np.ndarray (n_timesteps,)
            well_names: list[str]
    """
```

Требования:
- Парсить tNavigator-выгрузку через готовый драйвер (написать обёртку, формат на месте смотреть)
- Валидация через pydantic: все 150 моделей должны иметь одинаковые well_names, time_steps, n_θ
- Возвращать понятную ошибку, если хоть одна модель битая (битая = NaN в production, пустой файл, недостающие скважины)
- Логировать каждую модель: `loaded model_id=X, cluster=Y, n_NaN=Z`

**Task 0.2: Observations loader**

```python
def load_observations(
    rates_path: Path,
    cumulative_path: Path,
    noise_spec_path: Path,
) -> ObservationData:
    """
    Загружает исторические наблюдения и их ковариацию.
    
    Returns:
        ObservationData с полями:
            d_obs_rates: np.ndarray (n_d_rates,)
            d_obs_cum: np.ndarray (n_d_cum,)
            C_dd_rates: np.ndarray (n_d_rates, n_d_rates)  # диагональная
            C_dd_cum: np.ndarray (n_d_cum, n_d_cum)
            time_steps: np.ndarray
    """
```

**Task 0.3: State vector builder**

```python
def build_state_vector(
    theta: np.ndarray,
    u: np.ndarray | None,
    include_controls: bool = True,
) -> tuple[np.ndarray, StateVectorSchema]:
    """
    Собирает z = (θ, u) или z = θ, в зависимости от флага.
    Returns z (N, n_z) и схему для распаковки обратно.
    """
```

**Acceptance Task 0**:
- Все 150 моделей загружены, нет NaN
- Размерности согласованы: d_sim[i].shape == d_obs.shape для всех i
- pytest на синтетическом мини-датасете (20 моделей, 5 параметров, 10 наблюдений)

---

### Фаза 1 — ES-апдейт

**Task 1.1: Adaptive correlation-based localization**

```python
def adaptive_correlation_localization(
    Z: np.ndarray,      # (N, n_z) state vectors
    D: np.ndarray,      # (N, n_d) predicted observations
    N: int,
    method: Literal["hard", "soft_taper"] = "hard",
) -> np.ndarray:
    """
    Строит маску локализации L (n_z, n_d) по корреляциям на ансамбле.
    
    method="hard": L[i,j] = 1 если |corr(Z[:,i], D[:,j])| >= 3/sqrt(N), иначе 0
    method="soft_taper": плавный спад через cosine taper в окрестности порога
    
    Возвращает маску, которую потом умножают на K-элемент-в-элемент.
    """
```

Требования:
- При N=150 порог = 3/sqrt(150) = 0.2449
- Хранить полную матрицу корреляций для аудита
- Считать процент обнулённых элементов и логировать
- Опция `method="soft_taper"` — мягкий аналог для случаев, когда жёсткий порог слишком агрессивен

**Task 1.2: ES-апдейт с subspace-регуляризацией**

```python
def es_update(
    Z_prior: np.ndarray,    # (N, n_z)
    D_sim: np.ndarray,      # (N, n_d)
    d_obs: np.ndarray,      # (n_d,)
    C_dd: np.ndarray,       # (n_d, n_d) диагональная
    localization_mask: np.ndarray | None = None,
    subspace_energy: float = 0.99,
    seed: int = 42,
) -> ESUpdateResult:
    """
    Один ES-апдейт по формуле 5.13 Evensen:
        z_post[i] = z_prior[i] + K @ (d_obs + ε[i] - d_sim[i])
        K = C_zd @ inv(C_dd_ens + C_dd)
    
    С subspace-регуляризацией через SVD от D' с truncation на subspace_energy.
    
    Returns:
        ESUpdateResult с полями:
            Z_post: np.ndarray (N, n_z)
            K: np.ndarray (n_z, n_d)
            singular_values: np.ndarray
            n_components_kept: int
            perturbations: np.ndarray (N, n_d)
    """
```

Алгоритм (точно по книге):
1. Z' = Z_prior - mean(Z_prior, axis=0)
2. D' = D_sim - mean(D_sim, axis=0)
3. SVD: D' = U @ diag(s) @ Vt, обрезать на 99% энергии → s_r, U_r, Vt_r
4. Перtuрбации: ε ~ N(0, C_dd), N независимых сэмплов
5. C_dd_ens = D'.T @ D' / (N-1)
6. K = Z'.T @ D' @ inv((s_r² + (N-1) σ²)·I) @ U_r.T   (в subspace)
7. Применить L: K_loc = K * L
8. Z_post = Z_prior + K_loc @ (d_obs + ε - D_sim).T

**Task 1.3: QC-чеки**

```python
def run_qc_checks(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    cluster_ids: np.ndarray,
    schema: StateVectorSchema,
) -> QCReport:
    """
    Прогоняет полный набор QC-чеков. Возвращает QCReport с полями:
        spread_retention: pd.DataFrame с std_post/std_prior по каждой компоненте
        rank_prior: int
        rank_post: int
        n_collapse_components: int  # компоненты со spread_retention < 0.1
        mahalanobis_migration: np.ndarray (N,)
        bimodality_score: float  # для diagnostics
        cluster3_diagnostic: ClusterMigrationReport
        passed: bool
        warnings: list[str]
    """
```

Конкретные пороги:
- `spread_retention < 0.1` для хоть одной компоненты → ERROR (коллапс)
- `spread_retention > 1.5` для большинства компонент → WARNING (апдейт не сошёлся)
- `rank_post < N - 1` → WARNING (потеря независимости)
- Bimodality_score > 0.3 на mahalanobis-migration → INFO (нормально, но стоит посмотреть)

**Task 1.4: Cluster 3 diagnostic**

Отдельный диагностический модуль:
- Сравнить, насколько центроид кластера 3 в θ-пространстве смещается до и после Фазы 1
- Если ES снижает смещение → control uncertainty работает, делаем вывод в статью
- Если ES увеличивает смещение → это сигнал, что нужна Фаза 4 (APS-soft-category)
- Сохранить в `qc/cluster3_diagnostic.html` с интерактивными графиками (plotly)

**Acceptance Фаза 1**:
- ES-апдейт прошёл, все QC-чеки passed
- Z_post.npy сохранён, K.npy сохранён для аудита
- QC-отчёт сгенерирован
- pytest: на синтетическом датасете с известной truth — Z_post сходится к truth в пределах 1σ

---

### Фаза 2 — Отбор моделей

**Task 2.1: Mahalanobis-сортировка**

```python
def rank_by_parameter_change(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    C_zz_prior: np.ndarray | None = None,
) -> np.ndarray:
    """
    Возвращает индексы моделей в порядке убывания ||Δz||_M.
    Если C_zz_prior=None — использовать ансамблевую оценку.
    """
```

**Task 2.2: Linear proxy для forecast**

```python
def build_linear_proxy(
    Z: np.ndarray,         # (N, n_z)
    D_forecast: np.ndarray,  # (N, n_d_forecast) на подмножестве уже посчитанных
    subset_indices: np.ndarray,
) -> LinearProxy:
    """
    Строит S = C_zd_forecast / C_zz (ансамблевая чувствительность, Глава 4).
    Возвращает объект LinearProxy с методом predict(z_new) -> d_forecast_estimate.
    """
```

**Task 2.3: Compute planner**

```python
def plan_resimulation(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    budget: ComputeBudget,
) -> SimulationPlan:
    """
    На основе бюджета (n_models_to_resimulate) и сортировки выдаёт:
        - models_to_resimulate.csv: топ-X model_id'ов
        - models_proxy.csv: остальные + параметры для прокси
        - validation_subset.csv: 10 случайных из models_proxy для валидации
    """
```

**Task 2.4: Proxy validation**

После того, как пользователь пересчитал 10 валидационных моделей в tNavigator:

```python
def validate_proxy(
    proxy: LinearProxy,
    d_forecast_actual: np.ndarray,    # (10, n_d_forecast)
    validation_indices: np.ndarray,
) -> ProxyValidationReport:
    """
    Считает relative error прокси: |d_proxy - d_actual| / sigma_ensemble.
    Если медиана < 1 → прокси приемлемо.
    Если медиана > 2 → провал, нужно пересимулировать всех 150.
    """
```

**Acceptance Фаза 2**:
- Сгенерирован список моделей для пересчёта
- Прокси валидирован (или explicit сообщение, что валидация требует ручного пересчёта 10 моделей)

---

### Фаза 3 — Прогнозный блок (ablation)

**Task 3.1: Three setups configuration**

```yaml
# configs/experiment_setups.yaml
setups:
  setup1_naive:
    use_es_update: false
    use_localization: false
    use_control_uncertainty: false
    d_obs_type: "cumulative"
    description: "Baseline: текущий подход (перенос θ_adapt центроида)"
  
  setup2_localized:
    use_es_update: true
    use_localization: true
    use_control_uncertainty: false
    d_obs_type: "cumulative"
    description: "+ Adaptive correlation-based localization"
  
  setup3_full:
    use_es_update: true
    use_localization: true
    use_control_uncertainty: true
    d_obs_type: "hybrid"   # cumulative + годовые rate-snapshot
    description: "Полный книжный набор"
```

**Task 3.2: Forecast aggregation**

```python
def aggregate_forecast(
    d_forecast: np.ndarray,    # (N, n_timesteps, n_phases)
    quantiles: list[float] = [0.1, 0.5, 0.9],
) -> ForecastQuantiles:
    """
    Считает P10/P50/P90 по ансамблю на каждом шаге.
    """
```

**Task 3.3: Metrics**

```python
def compute_metrics(
    d_forecast: np.ndarray,    # (M, n_timesteps, n_phases)
    d_baseline: np.ndarray,    # (M_baseline, n_timesteps, n_phases) для width_ratio
    d_truth: np.ndarray | None,  # ВСЕГДА None в этом проекте — см. §3
) -> ForecastMetrics:
    """
    Считает:
        ВСЕГДА:
            width_ratio: (P90-P10)_post / (P90-P10)_baseline    per (метрика, время)
            median_shift: P50_post - P50_baseline               per (метрика, время)
            summary_per_metric: агрегаты по столбцам выше
            per_cluster_quantiles: P10/P50/P90 по кластерам

        УСЛОВНО (d_truth не None — в этом проекте не выполняется):
            coverage_p10p90: % шагов, где truth ∈ [P10, P90]
            crps_per_phase: CRPS по oil/water/gas
            cumulative_error: |∫d_pred - ∫d_truth| / ∫d_truth

    В этом проекте d_truth всегда None → coverage / CRPS / cumulative_error
    возвращаются как None. Это не TODO, это финальное состояние.
    Код для CRPS/coverage оставлен в репо с unit-тестами на синтетике
    и активируется автоматически, если d_truth когда-либо появится.
    """
```

CRPS через `scipy.stats` или ручная реализация (~10 строк) — реализован, **не используется в основном пайплайне**:

```
CRPS(F, y) = ∫ (F(x) - 1{x >= y})² dx
```

**Task 3.4: Train/val split — RETIRED**

Эта задача снята с повестки в сессии 005. Изначально предполагалась как fallback на случай отсутствия forecast-симуляций или truth. Обе предпосылки оказались ложными в обратную сторону: forecast-симуляции **есть** (123/150 моделей, 2019–2024), а truth — **нет вообще** и не появится. Hindcast на val-слайсе 2017–2018 не решает проблему отсутствия truth и при этом ухудшает ES, отнимая у него 2 года данных. Поэтому:

- Функция `split_history(...)` **не реализуется**.
- ES в Фазе 1 потребляет всю историю 2011–2018.
- Phase 3 ablation сравнивает **ансамбли между собой** (см. acceptance ниже), а не с правдой.
**Task 3.5: Run all three setups**

```python
def run_ablation(
    setups: dict[str, SetupConfig],
    ensemble_data: EnsembleData,
    observations: ObservationData,
    forecast: ForecastData,                       # 123/150 моделей, 2019–2024
    truth: TruthData | None = None,               # ВСЕГДА None в этом проекте
) -> AblationResults:
    """
    Гоняет три постановки последовательно (или параллельно через joblib).
    Возвращает AblationResults с per-setup d_forecast, квантилями и метриками
    (truth-independent — width_ratio, median_shift; truth-dependent остаются None).
    """
```

**Acceptance Фаза 3** (переработан в сессии 005 под no-truth режим):

- Три setup'а посчитаны на forecast-периоде (123 модели для setup1 baseline; 149 для setup2/setup3 через proxy).
- `outputs/forecast/metrics_summary.csv` готов и содержит width_ratio + median_shift по каждой (setup × метрика).
- Все 5 фигур присутствуют: fig01_pipeline, fig02_qc_spread, fig03_ablation_p10p90, fig04_cumulative_scatter, fig06_cluster3_migration (PNG 300 dpi + PDF vector). fig05_crps_time **не делается**.
- В sidecar `metrics_summary.csv.meta.yaml` записано `evaluation_mode: no_truth_baseline_only`.
- Setup2 и setup3 заведомо byte-identical (нет workflow controls) — это фиксируется в notes ablation-таблицы, не маскируется.
- Главный аналитический результат — таблица сравнения **формы прогнозного распределения** между setup'ами: насколько ES + локализация сужают/расширяют доверительный интервал, насколько сдвигают медиану. Это и есть claim статьи в no-truth режиме.
- **Никаких высказываний типа "Setup 2 калиброван лучше Setup 1" в статье быть не должно** — нет правды, не из чего делать такой вывод.
- Если width_ratio выходит больше 1 (POST шире baseline) — это сигнал асимметрии сравнения (детерминированный baseline vs ансамбль POST). До claim'а в статью нужна либо симметризация (прогон baseline через тот же proxy-пайплайн), либо явное объяснение асимметрии. **Не подгонять.**

---

### Фаза 4 — APS-soft-category (опционально, делаем после Фазы 3)

**Не включаем в первую итерацию**. Когда дойдём до Фазы 4:

```python
def aps_latent_truncation(
    cluster_weights: np.ndarray,    # (k=3,) априорные веса кластеров
) -> ApsParameterization:
    """
    Строит 1D-truncation map для k=3.
    Возвращает thresholds t1, t2 такие, что:
        Φ(t1) = w1, Φ(t2) = w1 + w2
    где Φ — CDF стандартного нормального.
    """

def category_from_latent(
    y: np.ndarray,    # (N,) GRF-сэмплы
    aps: ApsParameterization,
) -> np.ndarray:
    """
    Эмерджентная категория по y: y < t1 → 0, t1 ≤ y < t2 → 1, y ≥ t2 → 2.
    """
```

Дальше: включить y в state vector рядом с θ, прогнать ES, посмотреть, как меняется category.

---

## 7. Конфигурационная философия

Глобальные дефолты в `configs/default.yaml`:

```yaml
ensemble:
  N: 150
  n_clusters: 3
  cluster_sizes: [50, 50, 50]

es_update:
  subspace_energy: 0.99
  localization_threshold_factor: 3.0   # порог = factor/sqrt(N)
  localization_method: "hard"
  perturbation_seed: 42

selection:
  default_top_x: 80
  proxy_validation_n: 10

forecast:
  horizon_years: 10                    # подстраивать под truth
  phases: ["oil", "water", "gas"]
  
metrics:
  quantiles: [0.1, 0.5, 0.9]
  coverage_target: 0.8

io:
  cache_matrices: true
  cache_dir: "outputs/cache"
```

Любой параметр можно перебить через CLI: `cmp-ensemble run --phase 1 --localization-threshold-factor 2.5`.

---

## 8. CLI

```
cmp-ensemble --help
cmp-ensemble run --phase 0    # подготовка данных
cmp-ensemble run --phase 1    # ES-апдейт + QC
cmp-ensemble run --phase 2    # отбор моделей
cmp-ensemble run --phase 3    # ablation forecast
cmp-ensemble run --phase all
cmp-ensemble report           # сгенерировать HTML-отчёт по всем фазам
cmp-ensemble figures          # перегенерировать figures для статьи
```

Каждая команда логирует в `logs/<timestamp>.log` и в stdout с цветом (rich).

---

## 9. Тестирование

**Unit-тесты** (pytest):
- `test_es_update.py`: на синтетическом датасете с известным truth-θ — Z_post сходится к truth в пределах 1σ
- `test_localization.py`: при N=150 порог ровно 3/sqrt(150)=0.2449; на случайных данных обнуляется ~95% (по null-распределению)
- `test_metrics.py`: CRPS на дельта-функции = 0; на широком uniform = ширина/12; sanity checks
- `test_io.py`: на минимальном датасете 20 моделей всё грузится

**Integration test**:
- Полный пайплайн на синтетическом мини-датасете (20 моделей, 3 кластера, 5 параметров, 10 наблюдений). Время выполнения < 30 сек.

**Регрессионные графики**: pytest-mpl для проверки, что figures не ломаются.

---

## 10. Документация

- `README.md` — quickstart, как запустить пайплайн на готовых данных
- `docs/data_format.md` — спецификация входных файлов
- `docs/methodology.md` — краткое изложение методологии со ссылками на главы Evensen 2026
- `docs/troubleshooting.md` — типичные проблемы (collapse ансамбля, NaN в выгрузке, и т.п.)
- Docstrings во всех публичных функциях по google-стилю

---

## 11. Критерии приёмки всего проекта

- [ ] Все юнит-тесты проходят (`pytest -q`)
- [ ] Integration test `tests/test_integration_synthetic.py` проходит за < 30 сек
- [ ] На реальных 149 моделях:
  - QC-чеки Фазы 1 — все passed
  - Список моделей для Фазы 2 сгенерирован (`outputs/selection/models_to_resimulate.csv` и `models_proxy.csv` — partition без пересечений)
  - Proxy провалидирован: median relative error < 1.0 (через leave-one-out на 123 моделях с готовым forecast; ручной re-sim в tNavigator не требуется)
  - Три setup'а посчитаны на forecast-периоде 2019–2024; `metrics_summary.csv` готов и содержит width_ratio + median_shift по (setup × метрика)
  - Все **5** figures сгенерированы: fig01_pipeline, fig02_qc_spread, fig03_ablation_p10p90, fig04_cumulative_scatter, fig06_cluster3_migration (PNG 300 dpi + PDF vector в `outputs/article_assets/figures_v2/`)
  - Каждый артефакт под `outputs/forecast/` имеет sidecar с `evaluation_mode: no_truth_baseline_only`
- [ ] HTML-отчёт по проекту собран командой `cmp-ensemble report` (`outputs/report.html` + `outputs/qc/qc_report.html`)
- [ ] LaTeX-таблица ablation готова (`outputs/article_assets/ablation_table.tex`, компилируется через pdflatex standalone)
- [ ] README + 3 файла в `docs/` (data_format, methodology, troubleshooting) написаны
- [ ] `feature_list.json` синхронизирован с реальным состоянием репо (pre-commit hook не даёт расходиться)

**Чего НЕТ в списке приёмки** (явно, чтобы не возникало соблазна добавить):

- coverage_p10p90, CRPS, cumulative_error — **не оцениваются**: нет d_truth.
- "Setup 2/3 калиброван лучше Setup 1" — **не утверждается**: правды для калибровки нет.
- Train/val split — снят с повестки.
- fig05_crps_time — retired.

---

## 12. Что НЕ нужно делать

- Не реализовывать ESMDA с несколькими итерациями (только ES = 1 итерация). ESMDA с 4 итерациями — следующий шаг, если ES даст плохие результаты.
- Не реализовывать APS (Фаза 4) — только заглушка с TODO.
- Не интегрироваться с tNavigator-API. Только чтение готовых CSV-выгрузок.
- Не делать веб-интерфейс. CLI достаточно.
- Не делать distributed computing. Локально, на одной машине.

---

## 13. Что в первую очередь и в какой последовательности

1. Скелет проекта + pyproject.toml + конфиги
2. Task 0.1 + Task 0.2 + тесты на синтетике
3. Task 1.1 + Task 1.2 + тесты на синтетике
4. Task 1.3 + Task 1.4 + первый прогон QC на реальных 150
5. **STOP** — показать результаты пользователю, обсудить QC, скорректировать параметры
6. Task 2.1–2.4 + список моделей для пересчёта
7. **STOP** — пользователь пересчитывает в tNavigator
8. Task 3.1–3.5 + finally figures
9. **STOP** — финальная сборка отчёта

---

## 14. Контактные точки и допущения

Все исторические допущения (в v1 ТЗ) **разрешены** в ходе аудита сессий 002–005. Резюме:

- Формат tNavigator-выгрузки — **Excel** (`Показатели динамики.xlsx`, 150 листов; forecast в `decoded_results.xlsx` → кэш `forecast.h5`).
- Watt-truth для forecast-периода — **отсутствует, не появится**. Это финальное состояние датасета.
- Длина forecast-горизонта — **70 месяцев** (2019-01-01 → 2024-10-01).
- Compute-бюджет — **123/150 моделей досчитаны**, 27 отвалились (pressure depletion). Ручной re-sim не требуется: proxy валидируется leave-one-out на 123.
- `Адаптированный центроид →` (первая строка каждого листа в `models_near_adapted_centroids.xlsx`) — это reference centroid в θ-пространстве, общая отправная точка для всех 50 моделей кластера. Используется в Task 1.4 (диагностика смещения).

Пайплайн **уже работает** в режиме, который описан этой ревизией ТЗ. Дальнейшие подтверждения не нужны — заводить новые открытые клар-я следует только при реальной новой неоднозначности.

---

## 15. Что Claude Code должен спросить до начала работы

Все 5 оригинальных вопросов из v1 ТЗ **разрешены** (см. §14). Список оставлен в виде "журнала разрешённых вопросов" для аудита:

1. ~~Где лежат tNavigator-выгрузки?~~ → 4 Excel в корне репо (см. §3).
2. ~~Какие имена параметров?~~ → 9 параметров: THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP.
3. ~~Формат `production.csv`?~~ → Excel-листы, 97 строк × 581 колонка, `<metric>` для поля + `<metric> (<well>)` per-well.
4. ~~Доступен ли forecast-truth?~~ → **Нет**, и не появится. Это финал.
5. ~~Готов ли пользователь пересчитать 10 моделей вручную для валидации прокси?~~ → Не требуется: validation сделан leave-one-out на 123 готовых forecast-моделях; median rel err = 0.60 < 1.0 → PASS.

**Открытых вопросов нет.** Любой следующий Claude Code starts directly with the next unfinished feature in `feature_list.json` (use the priority field to pick the lowest).
