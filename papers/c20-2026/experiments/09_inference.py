"""Inference H1-H3 on blind test only (§11).

H1 Ridge: Clark-West HAC; H1 GBM + probabilistic dCRPS: moving block bootstrap
(weekly issuances, 8 weeks, sens. 4/13, B=10000, ratio-of-sums). H2: one-sided
95% lower bound of MSSS_damp(M*,W3-4). H3: CRPSS_clim per horizon + 90% coverage
criterion. Holm within families (H1:3, H2:1, H3:3).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement inference before running")


if __name__ == "__main__":
    main()
