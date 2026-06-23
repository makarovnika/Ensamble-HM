"""Closed-loop pure-ensemble history matching (ES-MDA) via tNavigator.

See TZ_closed_loop_ESMDA.md for the full specification. This package adds an
ES-MDA assimilation loop on top of the existing single-step ES machinery in
``cmp_ensemble.ensemble``; the forward model is abstracted so the same loop runs
against a linear-Gaussian test model or against tNavigator in production.
"""
from cmp_ensemble.closed_loop.esmda import ESMDAResult, esmda, uniform_alphas
from cmp_ensemble.closed_loop.forward import (
    ForwardModel,
    LinearGaussianForward,
    TNavForward,
)
from cmp_ensemble.closed_loop.prior import PriorResult, sample_prior
from cmp_ensemble.closed_loop.orchestrator import (
    ClosedLoopConfig,
    ClosedLoopResult,
    run_closed_loop,
)
from cmp_ensemble.closed_loop.forecast import (
    ClosedLoopForecast,
    run_forecast,
    summarize_forecast,
)
from cmp_ensemble.closed_loop.results_reader import (
    assemble_dsim,
    read_cumulative_dsim,
)

__all__ = [
    "ClosedLoopConfig",
    "ClosedLoopForecast",
    "ClosedLoopResult",
    "ESMDAResult",
    "ForwardModel",
    "LinearGaussianForward",
    "TNavForward",
    "PriorResult",
    "assemble_dsim",
    "esmda",
    "read_cumulative_dsim",
    "run_closed_loop",
    "run_forecast",
    "summarize_forecast",
    "sample_prior",
    "uniform_alphas",
]
