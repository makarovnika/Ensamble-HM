"""Closed-loop pure-ensemble history matching (ES-MDA) via tNavigator.

See TZ_closed_loop_ESMDA.md for the full specification. This package adds an
ES-MDA assimilation loop on top of the existing single-step ES machinery in
``cmp_ensemble.ensemble``; the forward model is abstracted so the same loop runs
against a linear-Gaussian test model or against tNavigator in production.
"""
from cmp_ensemble.closed_loop.esmda import ESMDAResult, esmda, uniform_alphas
from cmp_ensemble.closed_loop.forward import ForwardModel, LinearGaussianForward
from cmp_ensemble.closed_loop.prior import PriorResult, sample_prior

__all__ = [
    "ESMDAResult",
    "ForwardModel",
    "LinearGaussianForward",
    "PriorResult",
    "esmda",
    "sample_prior",
    "uniform_alphas",
]
