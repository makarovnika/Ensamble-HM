# ТЗ для Claude Code: ансамблевый прогноз для CMP / Watt Field

> **Контекст одной строкой**: у нас 150 уже посчитанных tNavigator-моделей (3 кластера × 50). Внутри кластера все 50 моделей наследуют одинаковый θ_adapt от центроида. Нужно реализовать post-hoc ES-апдейт + ablation-блок прогноза по методологии Evensen, Oliver, Hanea (2026), чтобы получить честный посteriорный ансамбль и сравнить три варианта прогноза.

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

## 3. Входные данные (предполагается, что есть на диске)

```
data/
├── ensemble_150/
│   ├── manifest.csv                 # 150 строк: model_id, cluster_id, source_seed, sim_path
│   ├── theta_adapt.csv              # 150 × n_θ, параметры адаптации (центроидные, дублируются)
│   ├── workflow_params.csv          # 150 × 12, исходные параметры воркфлоу
│   └── tnav_outputs/
│       └── <model_id>/              # 150 папок
│           ├── production.csv       # дебиты/BHP во времени, помесячно
│           ├── cumulative.csv       # накопленная добыча на конец каждого года
│           └── metadata.yaml        # имена скважин, единицы, тайм-степы
│
├── observations/
│   ├── historical_rates.csv         # 8 лет × ежемесячно, oil/water/gas/BHP по 17 скв
│   ├── historical_cumulative.csv    # накопленные на конец каждого года
│   └── noise_spec.yaml              # 15% Gaussian, диагональная C_dd
│
├── truth/                           # ОПЦИОНАЛЬНО, может отсутствовать
│   └── forecast_truth.csv           # truth-добыча на forecast-период (если есть)
│
├── geology/
│   ├── latents_v2.csv               # 9998 × 128, латенты CNN
│   ├── gmm_k3.csv                   # 9998 × 4: id, cluster, mahalanobis, prior_weight
│   └── workflow_combined.xlsx       # 9998 × 12, все параметры воркфлоу
│
└── configs/
    ├── theta_schema.yaml            # имена параметров адаптации, диапазоны, типы (continuous/discrete)
    └── well_layout.yaml             # 17 продюсеров + 6 инжекторов, координаты, типы
```

**Если каких-то файлов нет** — пайплайн должен явно сообщать, чего не хватает, и не падать с криптой ошибкой. Использовать `pydantic` для валидации схем.

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
│   ├── fig05_crps_time.png          # CRPS во времени
│   └── fig06_cluster3_migration.png # диагностика «съезда» кластера 3
│
└── article_assets/
    ├── ablation_table.tex           # LaTeX-таблица метрик
    └── figures_v2/                  # пережатые PNG для статьи
```

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
    d_forecast: np.ndarray,    # (N, n_timesteps, n_phases)
    d_truth: np.ndarray | None,  # (n_timesteps, n_phases), может быть None
    d_obs: np.ndarray,         # historical, для width_ratio
) -> ForecastMetrics:
    """
    Считает:
        coverage_p10p90: % шагов, где truth ∈ [P10, P90]
        crps_per_phase: CRPS по oil/water/gas
        width_ratio: width_post / width_prior
        cumulative_error: |∫d_pred - ∫d_truth| / ∫d_truth
    
    Если d_truth=None — coverage и cumulative_error возвращают None,
    остальные считаются.
    """
```

CRPS через `scipy.stats` или ручная реализация (~10 строк):

```
CRPS(F, y) = ∫ (F(x) - 1{x >= y})² dx
```

**Task 3.4: Train/val split fallback**

Если truth недоступен:

```python
def split_history(
    historical_data: ObservationData,
    train_years: int = 6,
    val_years: int = 2,
) -> tuple[ObservationData, ObservationData]:
    """
    Делит историю на train/val для эмулированного forecast.
    """
```

**Task 3.5: Run all three setups**

```python
def run_ablation(
    setups: dict[str, SetupConfig],
    ensemble_data: EnsembleData,
    observations: ObservationData,
    truth: TruthData | None,
) -> AblationResults:
    """
    Гоняет три постановки последовательно (или параллельно через joblib).
    Возвращает AblationResults со всеми метриками и P10/P50/P90.
    """
```

**Acceptance Фаза 3**:
- Три постановки посчитаны
- `metrics_summary.csv` готов
- Если truth есть — coverage и cumulative_error не None
- Postановка 3 даёт coverage ≥ 80% и CRPS ≤ Postановки 2 ≤ Postановки 1 (если нет — это ВАЖНЫЙ результат, фиксируем как есть, не подгоняем)

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

- [ ] Все юнит-тесты проходят
- [ ] Integration test проходит за < 30 сек
- [ ] На реальных 150 моделях:
  - QC-чеки Фазы 1 — все passed
  - Сгенерирован список моделей для Фазы 2
  - При наличии forecast-выгрузок — три постановки посчитаны, `metrics_summary.csv` готов
  - Все 6 figures сгенерированы
- [ ] HTML-отчёт по проекту собран командой `cmp-ensemble report`
- [ ] LaTeX-таблица ablation готова

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

**Допущения, которые надо подтвердить с пользователем**:
- Формат tNavigator-выгрузки: CSV / Excel / другой?
- Доступен ли Watt-truth для forecast периода?
- Длина forecast-горизонта?
- Compute-бюджет (всего 150 forecast-runs или меньше)?

**Если допущения не подтверждены** — пайплайн должен работать в наиболее общем варианте (cumulative-only, train/val split вместо truth, бюджет на все 150) и явно логировать, какой режим выбран.

---

## 15. Что Claude Code должен спросить до начала работы

1. Где лежат tNavigator-выгрузки? (путь к `manifest.csv`)
2. Какие имена параметров в `theta_schema.yaml`?
3. Какой формат `production.csv`? (структура колонок)
4. Доступен ли forecast-truth? Если да — путь.
5. Готов ли пользователь пересчитывать 10 моделей вручную для валидации прокси?

После ответов — начинать с Task 0.1, не пытаться угадать формат данных по примерам в этом ТЗ.
