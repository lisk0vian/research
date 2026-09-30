"""Metrics (§10). Deterministic + probabilistic on one quantile grid.

MAE/RMSE/ACC descriptive; MSSS vs Clim/Damp + Murphy decomposition (sample-mean
reference reported separately). CRPS via shared 19-quantile grid for all models
(Gneiting-Ranjan), CRPSS vs Clim/Damp, tercile RPSS, PIT, reliability,
50/90% coverage, sharpness. No fair scores (no finite ensembles).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement metrics before running")


if __name__ == "__main__":
    main()
