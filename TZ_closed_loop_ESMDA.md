# ТЗ — Closed-Loop Pure-Ensemble History Matching (ES-MDA) через tNavigator API

Версия: 1.0 (исполнительная спецификация для Claude Code).
Статус: утверждено к реализации. Заменяет черновик `TZ_pure_ensemble_HM.md`.
Методологический источник: Evensen, Oliver, Hanea (2026) — гл. 3.6 (MDA), 5–6 (субпространственный ES/ES-MDA/EnRML), 7 (локализация), 9 (нелинейность), 13 (REEK).
Связь с репо: новый модуль `src/cmp_ensemble/closed_loop/`, переиспользует `ensemble/{es_update,localization,subspace,state_vector}`, `io/observations.py`, `forecast/`. Не трогает существующий пост-хок пайплайн.

> Для Claude Code: соблюдай операционный цикл и Completion Gate из `CLAUDE.md`. Одна фича `in_progress` за раз. Не запускай tNavigator сам без явного разрешения пользователя — оркестратор пишет план запусков и ждёт; см. §10. Доказательства — в `outputs/closed_loop/`, не в чате.

---

## 1. Цель и отличие от текущего эксперимента

Текущий эксперимент: ручная WF-адаптация → 150 готовых моделей → один пост-хок ES над уже посчитанной динамикой.

Новый эксперимент: **замкнутый цикл**. Ансамбль θ → tNavigator (WF + расчёт) → d_sim (накопл. добыча) → шаг ES-MDA → новый θ → повтор n_α раз → постериорный ансамбль → прогноз post-2018. Адаптация делается самим ансамблевым методом, без ручной WF-настройки.

Результат для статьи: сравнение «pure-ensemble closed-loop ES-MDA» против «manual-WF + post-hoc ES» по качеству матча, реализму обновлений θ, ширине прогнозного коридора и стоимости (число прогонов симулятора).

## 2. Метод ассимиляции — ES-MDA (обоснование)

ES-MDA выбран как базовый (доказательная база из книги — в `TZ_pure_ensemble_HM.md` §2; кратко: рабочий метод нефтяных кейсов гл. 13–14; §6.4 «много коротких линейных шагов снижают влияние нелинейности»; прост; ≈ EnRML по Chen & Oliver 2013).

- n_α шагов (по умолчанию 4; диапазон 4–8). Равномерные веса α_i = n_α (Σ 1/α_i = 1); опция — геометрически убывающие.
- Каждый шаг = существующий `es_update` с эффективной ковариацией ошибки α_i·C_dd и пересэмплингом возмущений из N(d, α_i·C_dd) при отдельном seed.
- Адаптивная корреляционная локализация (гл. 7), порог 3/√N — `adaptive_correlation_localization`.
- Ассимилируем накопленную добычу (см. §5).
- ES-MDA(n_α=1) обязан совпадать с одиночным `es_update`.

Опционально (вторым методом для сравнения): IES / Subspace EnRML (гл. 6.1–6.2). Реализуется после приёмки ES-MDA, отдельной фичей.

## 3. Данные и пути (подтверждены инспекцией)

Проект tNavigator: `simulation models results/tNavigator project/все центроиды.snp`
(скрипт `111.py` ссылался на `…/api.snp` на D: — для closed-loop используем локальный `все центроиды.snp`; путь конфигурируем).

Результаты расчёта — **стандартный Eclipse summary**: `RESULTS/<model_name>/result.SMSPEC` + `result.UNSMRY` (он же `result.sum`).
Подтверждено `resdata.summary.Summary`: 1943 вектора, ключи `WOPT:<well>`, `WWPT:<well>`, `WGPT:<well>` (накопл. нефть/вода/газ по скважинам), `WBHP`, `WWCT`, `FOPT…`; даты **2011-01-01 → 2024-10-01**, 167 шагов (история 2011-2018 + прогноз до 2024 в одном расчёте).

Скважины: 17 добывающих (WELL1..WELL10, WELL1A, WELL1B, WELL2A, WELL3A, WELL4A, WELL5A) + 6 нагнетательных (INJ1..INJ6) + фиктивная `B` (фильтровать).

Имя модели/папки: `<cluster>_<wf>-<seed>` (напр. `0_4-32434`). Workflow на кластер: `clust_0_4`, `clust1_1`, `clust_2_1` (из `111.py`/`tnav_autorun.py`).

Параметры пробрасываются WF в include-файлы (из `model_file_list.txt`): `*_SWL.inc, *_SWCR.inc, *_SOWCR.inc, *_KRORW.inc, *_KRWR.inc, *_CORNOW.inc (N_OW), *_CORNW.inc (N_W), *_PERMX.inc, *_PORO.inc, *_NTG.inc, *_RP.inc` + геология через грид. Подтверждает, что relperm/контакты управляемы через θ.

Историч. наблюдения и C_dd: `Исторические значения.xlsx` + `configs/noise_spec.yaml` — переиспользуем `io/observations.py`.

## 4. Вектор параметров θ (гео + relperm/контакты)

Базовые значения и состав — `tnav_autorun.py` (`BASE_VARIABLES`, `VARYING_COLS`).

- Группа A — геология (9): THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP. Границы — `configs/theta_schema.yaml`.
- Группа B — relperm по сатурационным регионам: S_WL*, S_WCR*, S_OWCR*, K_RORW*, K_RWR*, N_OW* (CORNOW), N_W* (CORNW). KH* — уточнить смысл при реализации.
- Группа C — контакты/множители: WOC_DEPTH_S_1 (ВНК); опционально PERMX, F1..F9.

Prior: гео — из envelope schema; группы B/C — усечённое нормальное вокруг base со σ = rel_sigma·|base| (по умолч. 0.15), обрезка по физике (доли∈[0,1], экспоненты Кори>1, K_r∈[0,1]); множители — лог-нормально. Всё в `configs/closed_loop.yaml` + новый `configs/closed_loop_theta_schema.yaml`.

Открытые решения переносятся в §12.

## 5. Наблюдения d_obs и C_dd

- d_obs: накопл. добыча oil/water/gas по 17 добывающим на годовых якорях 2011-12-31 … 2018-12-31 (8 точек), как в текущем пайплайне (`d_obs_type: cumulative`).
- d_sim: те же WOPT/WWPT/WGPT по тем же скважинам и якорям, читаются из summary постериорных/итерационных расчётов.
- C_dd: диагональная, σ_d = 15%·|d_obs|, мягкий пол; из `configs/noise_spec.yaml`. Индекс (metric, well, time) согласован через `io/observations.py`.

## 6. Архитектура замкнутого цикла

```
sample_prior(N) ─► Θ⁰
repeat i = 0 .. n_α-1:
    D_i  = forward(Θ_i)            # tNavigator: WF+расчёт всех членов, чтение summary
    loc  = localization(Θ_i, D_i)  # адаптивная корреляционная
    Θ_i+1 = es_update(Θ_i, D_i, d_obs, α_i·C_dd, loc)   # один MDA-шаг
    checkpoint(outputs/closed_loop/iter_i/)
Θ_post = Θ_{n_α}
D_fore = forward_forecast(Θ_post)  # прогноз post-2018
quantiles + metrics + figures
```

`forward` — абстракция: в тестах линейно-гауссова, в проде вызывает tNavigator (§10). Чекпоинт каждой итерации (Θ_i, D_i, misfit, meta) для докатки после сбоя.

## 7. Модуль и файлы

```
src/cmp_ensemble/closed_loop/
  __init__.py
  prior.py        # sample_prior(schema, N, seed) → Θ⁰; обрезка по физике
  esmda.py        # esmda(Θ0, forward, d_obs, C_dd, n_alpha, weights, localization_fn, ...) → ESMDAResult
  forward.py      # ForwardModel протокол; LinearGaussianForward (тесты); TNavForward (прод)
  results_reader.py  # read_cumulative_dsim(results_dir, wells, anchors) через resdata → вектор d
  orchestrator.py # run_closed_loop(config): prior→iterate→posterior→forecast→artifacts
configs/
  closed_loop.yaml
  closed_loop_theta_schema.yaml
tnav_autorun.py   # доработка под run_member/run_ensemble + интеграция с results_reader
```

CLI: `cmp-ensemble closed-loop --cluster K [--n-alpha 4] [--N 100] [--dry-run]`.

## 8. Зависимости

`resdata` (чтение Eclipse summary) — добавить в `pyproject.toml`. `tNavigator_python_API` — только на машине пользователя (импорт локальный, не ломает тесты). Остальное — уже в проекте (numpy, pandas, pydantic, click).

## 9. Прогноз и метрики

- Прогноз post-2018 (2019-01 … 2024-10, есть в summary) для постериорного ансамбля.
- Квантили P10/P50/P90 — `forecast/aggregation.py`. Метрики width_ratio, median_shift; coverage/CRPS — если появится d_truth прогноза.
- Сравнение pure-ensemble vs post-hoc: совмещённые коридоры, таблица метрик, эволюция misfit по шагам ES-MDA, миграция θ prior→posterior.

## 10. Интерфейс к tNavigator (авто-режим)

`tnav_autorun.py` (уже без GUI): `open_session`, `run_member(θ)`, `run_ensemble(θ-matrix)`, ретраи, логи. Добавить `collect_results` через `results_reader.py` (resdata: `Summary(<result>.SMSPEC)` → `numpy_vector("WOPT:WELL..")` → накопл. на годовых якорях).

Политика запуска: оркестратор по умолчанию **пишет план запусков** `outputs/closed_loop/iter_i/run_plan.csv` и θ-матрицу, и при `--execute` (с явного согласия) вызывает `run_ensemble`. Без `--execute` — останавливается с инструкцией, чтобы пользователь сам запустил расчёт (соответствует правилу CLAUDE.md «не авто-запускать tNavigator»). Пользователь подтвердил желание авто-режима — флаг `--execute` его включает.

## 11. Фазы и Completion Gate

Каждая фаза → запись в `feature_list.json` + `claude-progress.md`; приёмка по `CLAUDE.md` (юнит-тест + синтетический интеграционный < 30 c + evidence-путь).

- **CL-A scaffold**: модуль-скелет, `configs/closed_loop*.yaml`, prior + схема θ (гео+relperm+контакты), синтетическая фикстура. Тест: prior в границах, формы.
- **CL-B esmda core** (приоритет): `esmda.py` + `forward.py(LinearGaussian)`. Тесты: ES-MDA(n_α=1) ≡ `es_update`; на линейно-гауссовой задаче с большим N постериорное среднее ≈ аналитический Калман (толеранс); misfit не растёт по шагам.
- **CL-C results reader**: `results_reader.py` на реальном `RESULTS/<model>` (есть в репо: `simulation models results/Experiment 2/300/...`). Тест: читает WOPT/WWPT/WGPT, форма d совпадает с d_obs-индексом, годовые якоря корректны.
- **CL-D tnav interface**: `tnav_autorun` ↔ reader; dry-run/mock без tNavigator. Тест: mock-forward проходит полный цикл.
- **CL-E orchestrator + CLI**: `run_closed_loop`, чекпоинты, `--execute`/план. Интеграционный тест на синтетике < 30 c.
- **CL-F forecast+metrics+figures**: коридоры, метрики, сравнение с пост-хок.
- **CL-G report/docs/QC**: HTML-роллап + раздел методологии.

## 12. Открытые решения (подтвердить по ходу; не блокируют CL-A/B)

1. Состав θ группы C: включать PERMX и F1–F9 или фиксировать.
2. Размер relperm-набора: все ~80 параметров по регионам или сокращённый (риск коллапса при N≈100–150 и большой d-размерности → опора на локализацию).
3. n_α и веса: 4 равномерных по умолчанию — подтвердить (или 8 / геометрические).
4. Размер ансамбля N для closed-loop: 100 / 150 / иное.
5. Параллелизм запусков членов: одновременно (пул) или последовательно — зависит от лицензии.
