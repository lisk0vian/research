"""Climatologies + seasonal dispersion (§7.1). Train-only per fold.

C2 harmonic (K=3) is the primary reference fixed a priori; C1/C3 are
sensitivity runs. Fits on daily training data, then aggregates to horizons.
Also estimates sigma_h,q and empirical tercile thresholds (±15-day window).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement climatologies before running")


if __name__ == "__main__":
    main()
