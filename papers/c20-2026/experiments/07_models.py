"""Models (§8). Direct strategy, one model per horizon h.

Clim (empirical ±15-day window), Damp (OLS by horizon×quarter, main skill
reference), Pers (deterministic only), Ridge_L/LG (gaussian sigma_h,q),
GBM_L/LG (L2 + quantile grid with rearrangement). M* selected on dev folds by
mean CRPS, frozen before blind B1-B2.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement models before running")


if __name__ == "__main__":
    main()
