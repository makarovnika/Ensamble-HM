"""Unit tests for the state vector builder (Task 0.3)."""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.ensemble.state_vector import build_state_vector, unpack_state_vector


def test_theta_only_round_trip() -> None:
    rng = np.random.default_rng(42)
    theta = rng.standard_normal((20, 9))
    z, schema = build_state_vector(
        theta, u=None, theta_names=[f"p{i}" for i in range(9)], include_controls=False
    )
    assert z.shape == (20, 9)
    assert schema.n_z == 9
    assert schema.control_slice is None
    theta_back, u_back = unpack_state_vector(z, schema)
    assert np.array_equal(theta_back, theta)
    assert u_back is None


def test_theta_and_controls_round_trip() -> None:
    rng = np.random.default_rng(0)
    N = 30
    theta = rng.standard_normal((N, 5))
    u = rng.standard_normal((N, 4))
    z, schema = build_state_vector(
        theta,
        u=u,
        theta_names=[f"t{i}" for i in range(5)],
        control_names=[f"u{i}" for i in range(4)],
        include_controls=True,
    )
    assert z.shape == (N, 9)
    assert schema.n_z == 9
    assert schema.theta_slice == (0, 5)
    assert schema.control_slice == (5, 9)
    theta_back, u_back = unpack_state_vector(z, schema)
    assert np.array_equal(theta_back, theta)
    assert u_back is not None
    assert np.array_equal(u_back, u)


def test_include_controls_false_drops_u_even_when_provided() -> None:
    theta = np.zeros((3, 2))
    u = np.ones((3, 1))
    z, schema = build_state_vector(
        theta,
        u=u,
        theta_names=["a", "b"],
        control_names=["c"],
        include_controls=False,
    )
    assert z.shape == (3, 2)
    assert schema.control_slice is None


def test_mismatched_n_raises() -> None:
    theta = np.zeros((10, 2))
    u = np.zeros((9, 1))   # wrong N
    with pytest.raises(ValueError):
        build_state_vector(theta, u=u, theta_names=["a", "b"], control_names=["c"])


def test_wrong_theta_names_length_raises() -> None:
    with pytest.raises(ValueError):
        build_state_vector(np.zeros((5, 3)), theta_names=["a", "b"])  # 2 names, 3 cols
