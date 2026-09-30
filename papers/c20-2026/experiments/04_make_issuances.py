"""Issuances, targets and embargo (§6 + §12.2).

Eval: weekly issuance (config weekday, default Monday). Training may use daily
issuance. Target A^h_d valid with >=5/7 (W1/W2) or >=10/14 (W3-4) valid days.
Training issuance d enters a fold only if d+28 < test start.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> None:
    raise NotImplementedError("stub: implement issuances before running")


if __name__ == "__main__":
    main()
