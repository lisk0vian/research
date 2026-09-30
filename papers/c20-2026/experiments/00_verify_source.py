"""V1-V6 source verification (§2.1). Reads config.yaml + data/raw/dataset.csv.

Checks timezone (V1), hour convention (V2), missing codes (V3), coverage (V4),
UBIGEO constancy (V5) and timestamp duplicates (V6). Writes a completeness
report to outputs/tables/T1_completeness.csv. Never imputes the target.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement V1-V6 checks before running")


if __name__ == "__main__":
    main()
