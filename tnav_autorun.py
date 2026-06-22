"""
tnav_autorun.py — автоматический запуск run_project_workflow в tNavigator через API.

Доработка 111.py: убран tkinter-GUI и ручной выбор кластера; подключение к
tNavigator вынесено из верхнего уровня в функции (модуль импортируется без
запуска симулятора); добавлены логирование, ретраи, dry-run и θ-driven путь
(можно подавать произвольный вектор параметров, а не только строки Excel) —
это нужно для closed-loop ES-MDA из src/cmp_ensemble/closed_loop/.

Использование (батч из Excel):
    python tnav_autorun.py --cluster 0 \
        --excel "C:/.../models_near_adapted_centroids.xlsx" \
        --exe   "C:/Program Files/tNavigator/26.1/tNavigator-con.exe" \
        --project "D:/.../api.snp"

Сухой прогон (без tNavigator, только проверка чтения Excel и сборки кода):
    python tnav_autorun.py --cluster 0 --excel "..." --dry-run

Как библиотека (для closed-loop):
    from tnav_autorun import open_session, run_member, run_ensemble
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Iterable, Mapping, Sequence

import pandas as pd

log = logging.getLogger("tnav_autorun")

# ─── КОНФИГ КЛАСТЕРОВ ─────────────────────────────────────────────────────────
CLUSTER_CONFIG = {
    0: {"sheet": "Кластер_0_адаптация", "workflow": "clust_0_4"},
    1: {"sheet": "Кластер_1_адаптация", "workflow": "clust1_1"},
    2: {"sheet": "Кластер_2_адаптация", "workflow": "clust_2_1"},
}

# ─── БАЗОВЫЕ (ФИКСИРОВАННЫЕ ПО УМОЛЧАНИЮ) ПЕРЕМЕННЫЕ ──────────────────────────
# В closed-loop любая из них может стать варьируемой (гео + relperm/контакты):
# тогда её значение приходит в theta-словарь и переопределяет базовое.
BASE_VARIABLES = {
    "WOC_DEPTH_S_1": 1654.148,
    "S_WL_1": 0.33991, "S_WL_1A": 0.206548, "S_WL_1B": 0.245538,
    "S_WL_2": 0.207338, "S_WL_2A": 0.167224, "S_WL_3A": 0.72974,
    "S_WL_3": 0.30867, "S_WL_4": 0.36244, "S_WL_4A": 0.286916,
    "S_WL_5": 0.262329, "S_WL_5A": 0.37349, "S_WL_6": 0.18483,
    "S_WL_7": 0.260561, "S_WL_8": 0.217341, "S_WL_9": 0.725854,
    "S_WL_10": 0.160999,
    "S_WCR_1": 0.141127, "S_WCR_1A": 0.122686, "S_WCR_1B": 0.125151,
    "S_WCR_2": 0.104888, "S_WCR_2A": 0.144501, "S_WCR_3": 0.115564,
    "S_WCR_3A": 0.12109, "S_WCR_4A": 0.133115, "S_WCR_5A": 0.108474,
    "S_WCR_4": 0.109934, "S_WCR_5": 0.124073, "S_WCR_6": 0.132252,
    "S_WCR_7": 0.120837, "S_WCR_8": 0.084099, "S_WCR_9": 0.077965,
    "S_WCR_10": 0.134354,
    "S_OWCR_1": 0.171533, "S_OWCR_1A": 0.14764, "S_OWCR_1B": 0.111373,
    "S_OWCR_2": 0.13257, "S_OWCR_2A": 0.196198, "S_OWCR_3": 0.0717,
    "S_OWCR_3A": 0.125472, "S_OWCR_4": 0.167411, "S_OWCR_4A": 0.082932,
    "S_OWCR_5": 0.15816, "S_OWCR_5A": 0.149765, "S_OWCR_6": 0.053982,
    "S_OWCR_7": 0.144036, "S_OWCR_8": 0.096821, "S_OWCR_9": 0.093273,
    "S_OWCR_10": 0.051633,
    "K_RORW_1": 0.596159, "K_RORW_1A": 0.545838, "K_RORW_1B": 0.571226,
    "K_RORW_2": 0.445014, "K_RORW_2A": 0.268857, "K_RORW_3": 0.69666,
    "K_RORW_3A": 0.395156, "K_RORW_4": 0.347832, "K_RORW_4A": 0.647903,
    "K_RORW_5": 0.430669, "K_RORW_5A": 0.815923, "K_RORW_6": 0.447775,
    "K_RORW_7": 0.236466, "K_RORW_8": 0.424485, "K_RORW_9": 0.518299,
    "K_RORW_10": 0.598461,
    "K_RWR_1": 0.27251, "K_RWR_1A": 0.421931, "K_RWR_1B": 0.466899,
    "K_RWR_2": 0.337904, "K_RWR_2A": 0.24844, "K_RWR_3": 0.1937,
    "K_RWR_3A": 0.331871, "K_RWR_4": 0.12651, "K_RWR_4A": 0.04751,
    "K_RWR_5": 0.43, "K_RWR_5A": 0.53, "K_RWR_6": 0.289862,
    "K_RWR_7": 0.508455, "K_RWR_8": 0.150216, "K_RWR_9": 0.601627,
    "K_RWR_10": 0.279498,
    "N_OW_1": 3.503195, "N_OW_1A": 4.522204, "N_OW_1B": 2.500565,
    "N_OW_2": 5.040748, "N_OW_2A": 4.811535, "N_OW_3": 4.258493,
    "N_OW_3A": 3.153047, "N_OW_4": 4.015782, "N_OW_4A": 3.858339,
    "N_OW_5": 3.821025, "N_OW_5A": 4.172627, "N_OW_6": 4.170026,
    "N_OW_7": 4.489678, "N_OW_8": 3.732282, "N_OW_9": 4.78086,
    "N_OW_10": 4.432331,
    "N_W_1": 5.568504, "N_W_1A": 4.646984, "N_W_1B": 2.339769,
    "N_W_2": 4.700365, "N_W_2A": 4.74229, "N_W_3": 5.368556,
    "N_W_3A": 4.288121, "N_W_4": 4.357647, "N_W_4A": 4.575009,
    "N_W_5": 2.915863, "N_W_5A": 3.393296, "N_W_6": 3.837268,
    "N_W_7": 3.919414, "N_W_8": 5.859011, "N_W_9": 4.101412,
    "N_W_10": 4.067756,
    "KH_1": 0.601518, "KH_1A": 0.730076, "KH_1B": 0.232132,
    "KH_2": 0.504526, "KH_2A": 0.565762, "KH_3A": 0.561799,
    "KH_3": 0.489331, "KH_4": 0.530018, "KH_4A": 0.46101,
    "KH_5": 0.4861, "KH_5A": 0.4, "KH_6": 0.532019,
    "KH_7": 0.519001, "KH_8": 0.486495, "KH_9": 0.351572,
    "KH_10": 0.329271,
    "PERMX": 6.371797,
    "F1": 0.482661, "F2": 0.443806, "F3": 0.504708,
    "F4": 0.552646, "F5": 0.185809, "F6": 0.78987038020933,
    "F7": 0.810714, "F8": 0.255031, "F9": 0.731442,
}

VARYING_COLS = [
    "THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS",
    "CHANNELS_WIDTH", "LEN", "AMPLITUDE", "RELATIVE", "PROP",
]


# ─── ЗАГРУЗКА Excel ──────────────────────────────────────────────────────────
def load_models(cluster_id: int, excel_path: str) -> pd.DataFrame:
    """Читает лист кластера: строка 3 — заголовки, данные с строки 4."""
    sheet = CLUSTER_CONFIG[cluster_id]["sheet"]
    df = pd.read_excel(excel_path, sheet_name=sheet, header=None)
    df.columns = df.iloc[3]
    df = df.iloc[4:].reset_index(drop=True)
    df["MODEL"] = df["MODEL"].astype(int)
    for col in VARYING_COLS:
        df[col] = pd.to_numeric(df[col])
    return df


# ─── ПОДКЛЮЧЕНИЕ К tNavigator ────────────────────────────────────────────────
def open_session(exe_path: str, project_path: str):
    """Запускает сервер tNavigator, открывает проект, запрашивает лицензии.

    Импорт tNavigator_python_API локальный — модуль остаётся импортируемым
    на машинах без tNavigator (для тестов/closed-loop dry-run).
    """
    import tNavigator_python_API as tnav  # noqa: WPS433 (локальный импорт намеренно)

    log.info("Запуск tNavigator: %s", exe_path)
    conn = tnav.Connection(path_to_exe=exe_path)
    log.info("Открываю проект: %s", project_path)
    project = conn.open_project(project_path)
    project.run_py_code(
        code='request_license_features (requested_features=[{"feature":"FEAT_GEOLOGY_DESIGNER"}])'
    )
    project.run_py_code(
        code='request_license_features (requested_features=[{"feature":"FEAT_MODEL_DESIGNER"}])'
    )
    return conn, project


# ─── ЗАПУСК ОДНОГО ЧЛЕНА ─────────────────────────────────────────────────────
def build_variables(theta: Mapping[str, float]) -> dict:
    """База + переопределения из theta-вектора (гео и/или relperm/контакты)."""
    variables = dict(BASE_VARIABLES)
    variables.update({k: float(v) for k, v in theta.items()})
    return variables


def run_member(
    project,
    workflow: str,
    model_id: int,
    theta: Mapping[str, float],
    *,
    save: bool = True,
) -> None:
    """Запускает run_project_workflow для одного θ-вектора."""
    variables_object = build_variables(theta)
    variable_types = {k: "real" for k in variables_object}
    code = (
        "run_project_workflow(\n"
        '    project_type="gt_project",\n'
        f'    project_name="model_{model_id}",\n'
        f'    workflow="{workflow}",\n'
        f"    variable_types={variable_types!r},\n"
        f"    variables_object={variables_object!r}\n"
        ")"
    )
    project.run_py_code(code=code, save=save)


# ─── ЦИКЛ ПО АНСАМБЛЮ ────────────────────────────────────────────────────────
def run_ensemble(
    project,
    workflow: str,
    model_ids: Sequence[int],
    thetas: Sequence[Mapping[str, float]],
    *,
    max_retries: int = 1,
    sleep_between: float = 0.0,
) -> dict[int, str]:
    """Прогоняет все θ-векторы. Возвращает {model_id: "ok"|"error: ..."}."""
    assert len(model_ids) == len(thetas), "model_ids и thetas разной длины"
    total = len(model_ids)
    status: dict[int, str] = {}
    for i, (mid, theta) in enumerate(zip(model_ids, thetas), start=1):
        attempt = 0
        while True:
            try:
                log.info("[%d/%d] MODEL=%s запуск", i, total, mid)
                run_member(project, workflow, mid, theta)
                status[mid] = "ok"
                break
            except Exception as exc:  # noqa: BLE001 — логируем и продолжаем ансамбль
                attempt += 1
                if attempt > max_retries:
                    log.error("MODEL=%s провален: %s", mid, exc)
                    status[mid] = f"error: {exc}"
                    break
                log.warning("MODEL=%s ретрай %d/%d (%s)", mid, attempt, max_retries, exc)
        if sleep_between:
            time.sleep(sleep_between)
    ok = sum(v == "ok" for v in status.values())
    log.info("Готово: %d/%d успешно", ok, total)
    return status


def collect_results(project, model_ids: Iterable[int]):
    """Сбор динамики (накопл. добыча по скважинам) обратно в Python.

    ВНИМАНИЕ: точный вызов экспорта зависит от вашей сборки tNavigator API.
    В прогнозном прогоне результаты сводились в decoded_results.xlsx — закрытие
    цикла ES-MDA должно вернуть d_sim в том же формате. Реализуется после того,
    как вы подтвердите способ экспорта (см. TZ_pure_ensemble_HM.md §9.4).
    """
    raise NotImplementedError(
        "Шаг экспорта результатов согласуется отдельно — см. ТЗ §9.4."
    )


# ─── CLI (тонкая обёртка, без диалогов) ──────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="Авто-запуск кластера в tNavigator")
    p.add_argument("--cluster", type=int, required=True, choices=list(CLUSTER_CONFIG))
    p.add_argument("--excel", required=True, help="models_near_adapted_centroids.xlsx")
    p.add_argument("--exe", help="путь к tNavigator-con.exe")
    p.add_argument("--project", help="путь к api.snp")
    p.add_argument("--dry-run", action="store_true", help="без tNavigator: проверка чтения/сборки")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    df = load_models(args.cluster, args.excel)
    workflow = CLUSTER_CONFIG[args.cluster]["workflow"]
    model_ids = df["MODEL"].tolist()
    thetas = [{c: float(r[c]) for c in VARYING_COLS} for _, r in df.iterrows()]
    log.info("Кластер %d | workflow=%s | моделей: %d", args.cluster, workflow, len(model_ids))

    if args.dry_run:
        sample = build_variables(thetas[0])
        log.info("DRY-RUN: первый член MODEL=%s, %d переменных", model_ids[0], len(sample))
        log.info("DRY-RUN: пример THICK=%.4f MAJ_R=%.2f", thetas[0]["THICK"], thetas[0]["MAJ_R"])
        return

    if not args.exe or not args.project:
        p.error("--exe и --project обязательны без --dry-run")
    conn, project = open_session(args.exe, args.project)
    run_ensemble(project, workflow, model_ids, thetas)


if __name__ == "__main__":
    main()
