from cmp_ensemble.viz.ablation import (
    build_latex_ablation_table,
    fig03_ablation_p10p90,
    fig04_cumulative_scatter,
)
from cmp_ensemble.viz.diagnostics import (
    fig01_pipeline,
    fig02_qc_spread,
    fig06_cluster3_migration,
    mirror_to_article_assets,
)
from cmp_ensemble.viz.tier_b import render_all_tier_b
from cmp_ensemble.viz.tier_c import (
    interactive_ablation,
    interactive_theta_explorer,
    polish_cluster3_hover,
    render_all_tier_c,
)

__all__ = [
    "build_latex_ablation_table",
    "fig01_pipeline",
    "fig02_qc_spread",
    "fig03_ablation_p10p90",
    "fig04_cumulative_scatter",
    "fig06_cluster3_migration",
    "mirror_to_article_assets",
    "interactive_ablation",
    "interactive_theta_explorer",
    "polish_cluster3_hover",
    "render_all_tier_b",
    "render_all_tier_c",
]
