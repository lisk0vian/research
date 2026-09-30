"""Output contract (§14). Reads outputs/ only, never recomputes.

T1 completeness/QC; T2 MSSS/CRPSS/RPSS with 95% CI on blind; T3 H1-H3 tests
(stat, raw/ Holm p, decision); T4 Murphy decomposition. F1 skill-vs-horizon;
F2 PIT + tercile reliability (M*); F3 skill by quarter/ENSO; F4 robustness
D1-D3 vs B1-B2.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement tables/figures before running")


if __name__ == "__main__":
    main()
