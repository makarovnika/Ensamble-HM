"""Unit tests for the closed-loop prior sampler (feature CL-A)."""
import numpy as np
import pytest

from cmp_ensemble.closed_loop.prior import sample_prior, load_theta_schema

SCHEMA = "configs/closed_loop_theta_schema.yaml"


def test_prior_shapes_and_determinism():
    a = sample_prior(SCHEMA, N=150, seed=42)
    b = sample_prior(SCHEMA, N=150, seed=42)
    assert a.Theta.shape == (150, a.n_z)
    assert a.n_z > 100, "full relperm set should give n_z >> geology-only 9"
    np.testing.assert_array_equal(a.Theta, b.Theta)            # deterministic by seed
    c = sample_prior(SCHEMA, N=150, seed=7)
    assert not np.array_equal(a.Theta, c.Theta)                # different seed differs


def test_geology_within_envelope():
    schema = load_theta_schema(SCHEMA)
    res = sample_prior(SCHEMA, N=400, seed=1)
    idx = {n: i for i, n in enumerate(res.names)}
    for p in schema["geology"]["parameters"]:
        col = res.Theta[:, idx[p["name"]]]
        lo, hi = p["range"]
        assert col.min() >= lo - 1e-9 and col.max() <= hi + 1e-9


def test_fractions_and_corey_respect_physics():
    res = sample_prior(SCHEMA, N=600, seed=2)
    idx = {n: i for i, n in enumerate(res.names)}
    # saturations / kr / KH / F : ∈ [0, 1]
    frac_prefixes = ("S_WL", "S_WCR", "S_OWCR", "K_RORW", "K_RWR", "KH", "F")
    for name in res.names:
        if name.startswith(frac_prefixes) and not name.startswith(("N_OW", "N_W")):
            col = res.Theta[:, idx[name]]
            assert col.min() >= 0.0 and col.max() <= 1.0, name
    # Corey exponents N_OW*/N_W* : ∈ [1, 8]
    for name in res.names:
        if name.startswith(("N_OW", "N_W")):
            col = res.Theta[:, idx[name]]
            assert col.min() >= 1.0 and col.max() <= 8.0, name


def test_contacts_positive_and_lognormal():
    res = sample_prior(SCHEMA, N=400, seed=3)
    idx = {n: i for i, n in enumerate(res.names)}
    assert res.Theta[:, idx["WOC_DEPTH_S_1"]].min() > 0.0
    assert res.Theta[:, idx["PERMX"]].min() > 0.0               # log-normal => strictly +


def test_groups_partition_columns():
    res = sample_prior(SCHEMA, N=50, seed=4)
    flat = res.groups["geology"] + res.groups["contacts"]
    for k, v in res.groups.items():
        if k not in ("geology", "contacts"):
            flat += v
    assert sorted(flat) == sorted(res.names)                   # groups exhaust names
    assert len(flat) == len(set(flat)) == res.n_z              # no duplicates
