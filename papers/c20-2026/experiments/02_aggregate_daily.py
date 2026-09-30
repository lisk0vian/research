"""Daily aggregation on local civil day UTC-5 (§3.2).

Builds TT_mean/max/min/DTR, HR/PP/FF means, RR_sum, vector-mean u/v with
completeness rules from config.daily_aggregation. Wind is never averaged in
degrees. Writes data/processed/daily.csv (gitignored, regenerable).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement daily aggregation before running")


if __name__ == "__main__":
    main()
