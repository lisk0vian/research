"""Local predictors X_L (§7.2). All dated <= d, as anomalies vs own climatology.

TT lags/means/A0, DTR/TTmax/TTmin, HR, log1p RR sums, PP level + tendency,
7-day u/v means, target-midpoint day-of-year sin/cos.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement X_L features before running")


if __name__ == "__main__":
    main()
