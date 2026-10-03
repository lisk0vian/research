# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Text report of a run: data checks, then the paper's result tables.

Called by the notebook's last cell (see colab.yaml `report`). Every section reads
files on its own and tolerates their absence: after a failed run, the report
still shows whatever the stages before the failure produced, and says what is
missing instead of crashing. A section that fails for any other reason prints
its traceback and makes the script exit 1, so the notebook records it in
errors.log.

Usage:
    python report.py
"""

from __future__ import annotations

import json
import traceback

import pandas as pd

from _common import DATA_DIR, OUTPUTS

TABLES = OUTPUTS / "tables"
PROCESSED = DATA_DIR / "processed"
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)

SECTIONS: list[tuple[str, object]] = []


def section(title: str):
    """Register a report section, run in order by main()."""
    def wrap(fn):
        SECTIONS.append((title, fn))
        return fn
    return wrap


def main() -> int:
    """Run every section; a missing file is a note, anything else a failure."""
    failures: list[str] = []
    for title, fn in SECTIONS:
        print(f"\n== {title} " + "=" * max(0, 70 - len(title)))
        try:
            fn()
        except FileNotFoundError as exc:
            print(f"[missing] {exc.filename}: not produced yet")
        except Exception:  # noqa: BLE001 - reported, and turned into exit 1
            traceback.print_exc()
            failures.append(title)
    if failures:
        print(f"\nreport sections failed: {', '.join(failures)}")
    return 1 if failures else 0


@section("Data")
def _data():
    d = pd.read_csv(PROCESSED / "daily.csv", parse_dates=["date"], dtype={"station": str})
    print(f"daily.csv: {len(d)} station-days, {int(d['valid'].sum())} valid")
    c = pd.read_csv(PROCESSED / "daily_clim.csv", parse_dates=["date"], dtype={"station": str})
    print(f"daily_clim.csv: {len(c)} evaluation days "
          f"({c['date'].min().date()}..{c['date'].max().date()})")
    print("A_C2 by test year (should centre near 0):")
    print(c.groupby(c["date"].dt.year)["A_C2"].agg(["mean", "std", "count"]).round(3).to_string())


@section("Issuances")
def _issuances():
    i = pd.read_csv(PROCESSED / "issuances.csv",
                    parse_dates=["issue_date", "target_start", "target_end"])
    ev = i[i["kind"] == "eval"]
    print(f"issuances.csv: {len(i)} rows | eval {len(ev)} | train {len(i) - len(ev)}")
    print(f"anti-leakage violations (target_start <= issue_date): "
          f"{int((i['target_start'] <= i['issue_date']).sum())}")
    print(ev.groupby(["fold", "horizon"])["valid_target"].agg(["sum", "count"]).to_string())


@section("Primary model and pooled skill")
def _skill():
    pm = OUTPUTS / "models" / "primary_model.json"
    info = json.loads(pm.read_text(encoding="utf-8"))
    print(f"M* = {info['primary_model']} (chosen on dev, frozen before the blind folds)")
    m = pd.read_csv(TABLES / "metrics_long.csv", dtype={"scope": str})
    sel = m[(m["experiment"] == "temporal") & (m["scope"] == "pooled")
            & (m["target"] == "TT_mean")]
    for role in ("dev", "blind"):
        print(f"\nCRPSS vs Damp | {role} | TT_mean, pooled stations")
        print(sel[sel["role"] == role].pivot(index="model", columns="horizon",
                                             values="CRPSS_damp").round(3).to_string())
    print("\nCRPSS vs Clim | blind")
    print(sel[sel["role"] == "blind"].pivot(index="model", columns="horizon",
                                           values="CRPSS_clim").round(3).to_string())


@section("T2 blind skill")
def _t2():
    t2 = pd.read_csv(TABLES / "T2_blind_skill.csv")
    print(t2[t2["metric"] == "CRPSS_damp"].round(3).to_string(index=False))


@section("T3 hypotheses")
def _t3():
    print(pd.read_csv(TABLES / "T3_hypotheses.csv").round(4).to_string(index=False))


@section("T5 LOSO gap")
def _t5():
    print(pd.read_csv(TABLES / "T5_loso_gap.csv").round(3).to_string(index=False))


@section("T8 CFSv2 calibration")
def _t8():
    print(pd.read_csv(TABLES / "T8_cfs_calibration.csv").round(3).to_string(index=False))


@section("T9 calibration (amendment A2, post hoc)")
def _t9():
    t9 = pd.read_csv(TABLES / "T9_calibration.csv")
    print("cov90 should sit in [0.85, 0.95]; k fitted on dev folds only")
    print(t9.pivot_table(index="variant", columns=["role", "horizon"], values="cov90")
          .round(3).to_string())
    print()
    print("CRPSS vs Clim")
    print(t9.pivot_table(index="variant", columns=["role", "horizon"], values="crpss_clim")
          .round(3).to_string())


@section("T10 Chronos diagnostic (amendment A2, post hoc)")
def _t10():
    t10 = pd.read_csv(TABLES / "T10_chronos_diagnostic.csv")
    print(t10[["role", "check", "scope", "paths", "observed", "metric"]]
          .round(3).to_string(index=False))


@section("T11 Chronos precision and scale (amendment A2, post hoc, D3)")
def _t11():
    t11 = pd.read_csv(TABLES / "T11_chronos_sensitivity.csv")
    show = t11[t11["metric"].str.startswith(("cov90", "path SD"))]
    print(show.pivot_table(index=["check", "scope", "metric"], columns="variant",
                           values="paths").round(3).to_string())


@section("Figures")
def _figures():
    figs = sorted((OUTPUTS / "figures").glob("F*.png"))
    print("\n".join(f.name for f in figs) if figs else "[missing] outputs/figures/F*.png")


if __name__ == "__main__":
    raise SystemExit(main())
