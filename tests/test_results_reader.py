"""Unit tests for the Eclipse-summary cumulative reader (feature CL-C)."""
import glob
from datetime import datetime

import numpy as np
import pytest

from cmp_ensemble.closed_loop.results_reader import (
    METRIC_TO_ECLIPSE,
    assemble_dsim,
    interp_cumulative,
    read_cumulative_dsim,
)


class FakeSummary:
    """Duck-typed Eclipse summary for testing assemble_dsim without resdata."""

    def __init__(self, dates, vectors):
        self._dates = list(dates)
        self._vectors = {k: np.asarray(v, float) for k, v in vectors.items()}

    @property
    def dates(self):
        return self._dates

    def numpy_vector(self, key):
        return self._vectors[key]

    def has_key(self, key):
        return key in self._vectors


def _fake():
    dates = [datetime(2011, 1, 1), datetime(2014, 1, 1), datetime(2018, 12, 13)]
    # cumulative (monotonic) ramps; gas = 10x oil so columns are distinguishable
    vecs = {
        "WOPT:WELL1": [0.0, 100.0, 200.0],
        "WWPT:WELL1": [0.0, 30.0, 80.0],
        "WGPT:WELL1": [0.0, 1000.0, 2000.0],
        "WOPT:WELL2": [0.0, 50.0, 60.0],
        "WWPT:WELL2": [0.0, 10.0, 25.0],
        "WGPT:WELL2": [0.0, 500.0, 600.0],
    }
    return FakeSummary(dates, vecs)


def test_assemble_preserves_cum_index_order():
    s = _fake()
    cum_index = [
        ("Накопл. нефть", "WELL1", datetime(2014, 1, 1)),
        ("Накопл. газ", "WELL2", datetime(2014, 1, 1)),
        ("Накопл. вода", "WELL1", datetime(2011, 1, 1)),
    ]
    d = assemble_dsim(s, cum_index)
    assert d.shape == (3,)
    np.testing.assert_allclose(d, [100.0, 500.0, 0.0])   # order follows cum_index


def test_year_end_anchor_past_last_step_clamps():
    s = _fake()
    # anchor 2018-12-31 is past the last simulated step 2018-12-13 → clamp to last
    v = interp_cumulative(s, "WOPT:WELL1", datetime(2018, 12, 31))
    assert v == 200.0
    # an interior anchor interpolates linearly between bracketing dates
    mid = interp_cumulative(s, "WOPT:WELL1", datetime(2012, 12, 31))
    assert 0.0 < mid < 100.0


def test_missing_key_raises_or_nans():
    s = _fake()
    cum_index = [("Накопл. нефть", "WELL_ABSENT", datetime(2014, 1, 1))]
    with pytest.raises(KeyError):
        assemble_dsim(s, cum_index)
    d = assemble_dsim(s, cum_index, missing="nan")
    assert np.isnan(d[0])


def test_unknown_metric_raises():
    s = _fake()
    with pytest.raises(KeyError):
        assemble_dsim(s, [("Накопл. БЕЗ_КАРТЫ", "WELL1", datetime(2014, 1, 1))])


def test_metric_map_covers_three_cumulatives():
    assert set(METRIC_TO_ECLIPSE.values()) == {"WOPT", "WWPT", "WGPT"}


# ── Real-data test (skipped if resdata or the in-repo summary is unavailable) ──
def _real_smspec():
    hits = glob.glob(
        "simulation models results/3 centroids with 4 model near by/**/RESULTS/*/result.SMSPEC",
        recursive=True,
    )
    return hits[0] if hits else None


@pytest.mark.skipif(_real_smspec() is None, reason="in-repo Eclipse summary not present")
def test_reads_real_summary_shape_and_anchors():
    pytest.importorskip("resdata")
    smspec = _real_smspec()
    producers = ["WELL1", "WELL3", "WELL7"]
    anchors = [datetime(y, 12, 31) for y in range(2011, 2019)]   # 8 year-ends
    cum_index = [
        (metric, well, t)
        for metric in ("Накопл. нефть", "Накопл. вода", "Накопл. газ")
        for well in producers
        for t in anchors
    ]
    d = read_cumulative_dsim(smspec, cum_index)
    assert d.shape == (3 * 3 * 8,)
    assert np.all(np.isfinite(d))
    assert np.all(d >= 0.0)                                       # cumulative ≥ 0
    # cumulative is monotonic non-decreasing over the 8 anchors per (metric, well)
    per = d.reshape(3, 3, 8)
    assert np.all(np.diff(per, axis=2) >= -1e-6)
