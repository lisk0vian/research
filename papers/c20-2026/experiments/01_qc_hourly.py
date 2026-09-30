"""Hourly quality control (§3.1). Reads config.qc_hourly.

Flags out-of-range values, TT steps > threshold and stuck-sensor runs.
Flagged values become missing. Target is never imputed.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement hourly QC flags before running")


if __name__ == "__main__":
    main()
