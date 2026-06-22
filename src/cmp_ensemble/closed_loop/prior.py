"""Prior sampler for the closed-loop ES-MDA θ-vector (TZ_closed_loop_ESMDA.md §4).

Builds Θ⁰ (N, n_z) from ``configs/closed_loop_theta_schema.yaml``:

* Group A — geology (9): envelope-uniform ``U(lo, hi)``.
* Group B — relperm (full set): truncated-normal around the base value from
  ``tnav_autorun.BASE_VARIABLES`` with ``σ = rel_sigma·|base|``, clipped by the
  per-constraint physics bounds (fractions ∈ [0,1], Corey exponents ∈ [1,8]).
* Group C — contacts/multipliers: WOC depth (positive truncated-normal), PERMX
  (log-normal), F1..F9 (fractions).

The ordering of columns in Θ is deterministic and exposed via ``PriorResult.names``
so the same index maps a column to a θ-key for every downstream consumer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

log = logging.getLogger(__name__)


@dataclass
class PriorResult:
    """Sampled prior ensemble plus the metadata to interpret its columns."""

    Theta: np.ndarray                      # (N, n_z)
    names: list[str]                       # length n_z, column → θ-key
    groups: dict[str, list[str]] = field(default_factory=dict)  # group → names

    @property
    def n_z(self) -> int:
        return self.Theta.shape[1]


def _base_variables() -> dict[str, float]:
    """Base θ values; imported lazily so prior.py stays import-safe in tests."""
    from tnav_autorun import BASE_VARIABLES

    return dict(BASE_VARIABLES)


def _expand_prefix(prefix: str, base: dict[str, float]) -> list[str]:
    """All base keys belonging to a group prefix (``S_WL`` → S_WL_1.., ``F`` → F1..)."""
    out = []
    for k in base:
        if k == prefix:
            continue
        tail = k[len(prefix):]
        if k.startswith(prefix + "_") or (k.startswith(prefix) and tail.isdigit()):
            out.append(k)
    return sorted(out)


def _trunc_normal(rng, mean, sigma, lo, hi, size):
    """Truncated normal via rejection, with a clip fallback for stubborn tails."""
    out = np.empty(size)
    todo = np.arange(size)
    for _ in range(50):
        draw = rng.normal(mean, sigma, size=todo.size)
        ok = (draw >= lo) & (draw <= hi)
        out[todo[ok]] = draw[ok]
        todo = todo[~ok]
        if todo.size == 0:
            break
    if todo.size:                      # residual stragglers: clip into the box
        out[todo] = np.clip(rng.normal(mean, sigma, size=todo.size), lo, hi)
    return out


def load_theta_schema(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def sample_prior(
    schema_path: str | Path,
    N: int,
    *,
    seed: int = 42,
    base: dict[str, float] | None = None,
) -> PriorResult:
    """Sample the closed-loop prior ensemble Θ⁰ of shape (N, n_z)."""
    schema = load_theta_schema(schema_path)
    base = _base_variables() if base is None else dict(base)
    rel_sigma = float(schema.get("rel_sigma", 0.15))
    cons = schema["constraints"]
    rng = np.random.default_rng(seed)

    cols: list[np.ndarray] = []
    names: list[str] = []
    groups: dict[str, list[str]] = {}

    # ── Group A: geology — envelope-uniform ──────────────────────────────────
    geo_names = []
    for p in schema["geology"]["parameters"]:
        lo, hi = p["range"]
        cols.append(rng.uniform(lo, hi, size=N))
        names.append(p["name"])
        geo_names.append(p["name"])
    groups["geology"] = geo_names

    def _bounds(constraint: str) -> tuple[float, float]:
        c = cons[constraint]
        return float(c["lo"]), float(c["hi"])

    def _add_truncnorm(key: str, constraint: str) -> None:
        b = base[key]
        sigma = rel_sigma * abs(b)
        lo, hi = _bounds(constraint)
        cols.append(_trunc_normal(rng, b, sigma, lo, hi, N))
        names.append(key)

    def _add_lognormal(key: str, sigma_log: float) -> None:
        b = base[key]
        cols.append(b * np.exp(rng.normal(0.0, sigma_log, size=N)))
        names.append(key)

    # ── Group B: relperm ─────────────────────────────────────────────────────
    for g in schema["relperm"]["groups"]:
        prefix, constraint = g["prefix"], g["constraint"]
        members = _expand_prefix(prefix, base)
        for key in members:
            _add_truncnorm(key, constraint)
        groups[prefix] = members

    # ── Group C: contacts / multipliers ──────────────────────────────────────
    contact_names = []
    for p in schema["contacts"]["parameters"]:
        if "prefix" in p:
            members = _expand_prefix(p["prefix"], base)
            for key in members:
                _add_truncnorm(key, p["constraint"])
                contact_names.append(key)
        else:
            key, constraint = p["name"], p["constraint"]
            if constraint == "lognormal":
                _add_lognormal(key, float(cons["lognormal"]["sigma_log"]))
            else:
                _add_truncnorm(key, constraint)
            contact_names.append(key)
    groups["contacts"] = contact_names

    Theta = np.column_stack(cols)
    log.info("Prior sampled: N=%d n_z=%d (geology=%d relperm+contacts=%d)",
             N, Theta.shape[1], len(geo_names), Theta.shape[1] - len(geo_names))
    return PriorResult(Theta=Theta, names=names, groups=groups)
