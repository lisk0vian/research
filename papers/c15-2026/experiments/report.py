"""Text report of a c15-2026 run: training status, stage index, quality gates.

Called by the notebook's last cell (colab.yaml `report`). Every section tolerates
missing files, so it also reports on a run that stopped half way.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", HERE.parent / "outputs"))
CFG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8")) or {}


def training_status() -> None:
    print("== Training status " + "=" * 52)
    models_dir = OUTPUT_DIR / "models"
    active = (CFG.get("training") or {}).get("active_models") or []
    print(f"{'model':<16}{'status':<10}{'trials':<12}{'test f1':<10}tau")
    for m in active:
        trials = ((CFG.get("models") or {}).get(m) or {}).get("trials", "-")
        mp, hp = models_dir / f"train_{m}_manifest.json", models_dir / f"train_{m}_trials.json"
        if mp.exists():
            s = json.loads(mp.read_text(encoding="utf-8")).get("summary", {})
            print(f"{m:<16}{'done':<10}{trials!s:<12}{round(s.get('f1_test', 0.0), 4)!s:<10}"
                  f"{s.get('tau_star', '-')}")
        elif hp.exists():
            done = len(json.loads(hp.read_text(encoding="utf-8")))
            print(f"{m:<16}{'running':<10}{f'{done}/{trials}':<12}{'-':<10}-")
        else:
            print(f"{m:<16}{'pending':<10}{trials!s:<12}{'-':<10}-")


def stage_index() -> None:
    print("\n== Stage index (outputs/manifest_index.json) " + "=" * 25)
    path = OUTPUT_DIR / "manifest_index.json"
    if not path.exists():
        print("[missing] manifest_index.json: no stage has finished yet")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for stage, entry in (data.items() if isinstance(data, dict) else []):
        print(f"- {stage}: {entry.get('seccion_paper')} -> {entry.get('output_dir')}")
    for p in sorted((OUTPUT_DIR / "tables").glob("*")):
        print(f"  {p.name}  {p.stat().st_size} bytes")


def quality_gates() -> None:
    print("\n== Quality gates (config.yaml) " + "=" * 40)
    print(yaml.dump(CFG.get("quality_gates"), allow_unicode=True).rstrip())
    tm = OUTPUT_DIR / "tables" / "train_manifest.json"
    if tm.exists():
        metrics = json.loads(tm.read_text(encoding="utf-8")).get("metrics", {})
        print(json.dumps(metrics, indent=2, ensure_ascii=False)[:3000])
    else:
        print("[missing] tables/train_manifest.json: train has not finished")


if __name__ == "__main__":
    training_status()
    stage_index()
    quality_gates()
