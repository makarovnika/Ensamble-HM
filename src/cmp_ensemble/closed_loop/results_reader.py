"""Read cumulative production d_sim from tNavigator Eclipse summary (CL-C).

tNavigator writes a standard Eclipse summary per model run:
``RESULTS/<run_name>/result.SMSPEC`` + ``result.UNSMRY``. The cumulative
production vectors are ``WOPT:<well>`` (oil), ``WWPT:<well>`` (water),
``WGPT:<well>`` (gas). This module turns such a summary into the flat d-vector
expected by the ES-MDA loop, in the *exact* (metric, well, time) order pinned by
the observation ``cum_index`` so d_sim and d_obs are entry-for-entry comparable.

Two robustness concerns handled here:

* **Non-ASCII paths.** The resdata C backend fails to open cases under Cyrillic
  directories (the in-repo project lives under ``все центроиды.snf``). When the
  path is non-ASCII we copy ``result.SMSPEC``/``.UNSMRY`` to an ASCII temp dir
  and open from there.
* **Year-end anchors past the last simulated step.** A history-only run ends at
  2018-12-13, just short of the 2018-12-31 anchor. Cumulative production is
  monotonic, so we clamp out-of-range anchors to the nearest endpoint rather
  than raising (``Summary.get_interp`` would raise).

The assembly logic (:func:`assemble_dsim`) is decoupled from resdata via the
:class:`SummaryLike` protocol so it can be unit-tested with a mock summary.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Cumulative metric label (dynamics-side, canonical) → Eclipse summary keyword.
METRIC_TO_ECLIPSE: dict[str, str] = {
    "Накопл. нефть": "WOPT",
    "Накопл. вода": "WWPT",
    "Накопл. газ": "WGPT",
}


class SummaryLike(Protocol):
    """Minimal duck-typed view of an Eclipse summary (resdata.summary.Summary)."""

    @property
    def dates(self) -> list[datetime]: ...

    def numpy_vector(self, key: str) -> np.ndarray: ...

    def has_key(self, key: str) -> bool: ...


def _is_ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def interp_cumulative(
    summary: SummaryLike, key: str, when: datetime, *, date_ordinals: np.ndarray | None = None
) -> float:
    """Cumulative value of ``key`` at time ``when``, clamped to the data range.

    Cumulative production is monotonic non-decreasing, so clamping an anchor that
    falls past the last simulated step to the final value is the correct estimate
    (the run simply stopped a few days early).
    """
    vec = np.asarray(summary.numpy_vector(key), dtype=float)
    if date_ordinals is None:
        date_ordinals = np.array(
            [pd.Timestamp(d).toordinal() for d in summary.dates], dtype=float
        )
    x = float(pd.Timestamp(when).toordinal())
    # np.interp clamps to endpoints outside [x0, x_n] by default — exactly the
    # behaviour we want for cumulative production.
    return float(np.interp(x, date_ordinals, vec))


def assemble_dsim(
    summary: SummaryLike,
    cum_index: Sequence[tuple[str, str, datetime]],
    *,
    metric_map: dict[str, str] | None = None,
    missing: str = "raise",
) -> np.ndarray:
    """Build the flat d_sim vector in the order pinned by ``cum_index``.

    Parameters
    ----------
    cum_index : list of (metric_label, well, time). The canonical ordering — the
        same object that pins d_obs in ``io.observations.load_observations``.
    missing : "raise" | "nan" — behaviour when a summary key is absent.
    """
    metric_map = metric_map or METRIC_TO_ECLIPSE
    date_ordinals = np.array(
        [pd.Timestamp(d).toordinal() for d in summary.dates], dtype=float
    )
    out = np.empty(len(cum_index), dtype=float)
    for i, (metric, well, when) in enumerate(cum_index):
        kw = metric_map.get(metric)
        if kw is None:
            raise KeyError(f"no Eclipse keyword for metric {metric!r}")
        key = f"{kw}:{well}"
        if not summary.has_key(key):
            if missing == "nan":
                out[i] = np.nan
                continue
            raise KeyError(f"summary missing key {key!r}")
        out[i] = interp_cumulative(summary, key, when, date_ordinals=date_ordinals)
    return out


def open_summary(smspec_path: str | Path, *, ascii_workaround: bool = True):
    """Open an Eclipse summary via resdata, copying past non-ASCII paths.

    The resdata import is local so this module imports on machines without it
    (tests use a mock summary). Returns a ``(summary, cleanup)`` pair; call
    ``cleanup()`` to remove any temp copy.
    """
    from resdata.summary import Summary  # local import — optional dependency

    smspec_path = Path(smspec_path)
    if ascii_workaround and not _is_ascii(str(smspec_path)):
        tmp = Path(tempfile.mkdtemp(prefix="rd_ascii_"))
        stem = smspec_path.stem
        for suffix in (".SMSPEC", ".UNSMRY"):
            src = smspec_path.with_suffix(suffix)
            if src.exists():
                shutil.copy2(src, tmp / f"{stem}{suffix}")
        summary = Summary(str(tmp / f"{stem}.SMSPEC"))
        return summary, lambda: shutil.rmtree(tmp, ignore_errors=True)
    return Summary(str(smspec_path)), lambda: None


def find_smspec(results_dir: str | Path, run_name: str | None = None) -> Path:
    """Locate ``result.SMSPEC`` under a model's RESULTS directory."""
    results_dir = Path(results_dir)
    pattern = "result.SMSPEC"
    cands = sorted(results_dir.rglob(pattern))
    if run_name is not None:
        cands = [c for c in cands if run_name in c.parts]
    if not cands:
        raise FileNotFoundError(f"no {pattern} under {results_dir}")
    return cands[0]


def read_cumulative_dsim(
    smspec_path: str | Path,
    cum_index: Sequence[tuple[str, str, datetime]],
    *,
    metric_map: dict[str, str] | None = None,
    missing: str = "raise",
) -> np.ndarray:
    """End-to-end: open a real summary and assemble its d_sim vector."""
    summary, cleanup = open_summary(smspec_path)
    try:
        return assemble_dsim(summary, cum_index, metric_map=metric_map, missing=missing)
    finally:
        cleanup()
