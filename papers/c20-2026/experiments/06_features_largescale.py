"""Large-scale predictors G (§7.2) with operational latencies.

Weekly Nino 3.4 / 1+2 (center <= d-7), RMM1/2 at d-1 (provider TO_VERIFY),
ERA5 PCs at d-5 refit per fold on training only (k=5, sensitivity 3/10;
domain/variables TO_CONFIRM_D4). ONI/ICEN excluded (centered smoothing leak).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement G features before running")


if __name__ == "__main__":
    main()
