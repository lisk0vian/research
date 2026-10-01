"""Feature Engineering Stage — 14 declared derived vars (OUR inferred formulas).

Reads silver consolidated via the consolidation manifest (artifact_path),
adds the 14 derived columns from config feature_engineering.derived, writes
silver engineered parquet. First-year lags are NaN by construction (no
history) and left for preprocessing to impute+flag honestly.
"""
import traceback
from pathlib import Path

import pandas as pd
import yaml

from src.paths import OUTPUT_DIR
from src.stages._io import (
    append_errors_entry,
    get_data_dir,
    get_output_base,
    load_upstream,
    log_line,
    new_run_log,
    read_manifest,
    resolve_context,
    write_manifest_atomic,
)
from src.stages.base import Stage
from src.stages.registry import register_stage


def _add_derived(df: pd.DataFrame, group_col: str, log) -> pd.DataFrame:
    import numpy as np

    out = df.copy()
    ing = pd.to_numeric(out["ingresado"], errors="coerce")
    ate = pd.to_numeric(out["atendido"], errors="coerce").fillna(0.0)
    out["saldo_casos"] = ing - ate
    out["tasa_atencion"] = np.where(ing > 0, ate / ing.where(ing > 0, 1.0), 0.0)
    out["ratio_saldo"] = np.where(ing > 0, out["saldo_casos"] / ing.where(ing > 0, 1.0), 0.0)
    out["anio_centrado"] = out["anio"] - float(out["anio"].mean())
    out["post_pandemia"] = (out["anio"] >= 2021).astype(int)
    out["periodo_pandemia_2020"] = (out["anio"] == 2020).astype(int)
    for a, b, name in (
        ("distrito_fiscal", "tipo_caso", "inter_distrito_tipo_caso"),
        ("materia", "tipo_fiscalia", "inter_materia_tipo_fiscalia"),
        ("tipo_fiscalia", "especialidad", "inter_tipo_fiscalia_especialidad"),
    ):
        out[name] = out[a].fillna("missing").astype(str) + "|" + out[b].fillna("missing").astype(str)
    # Lagged district-year aggregates: yearly group sums, expanding mean
    # shifted by one year, growth vs previous year aggregate. First year NaN.
    yearly = (
        out.assign(_saldo=out["saldo_casos"])
        .groupby([group_col, "anio"], as_index=False)
        .agg(_ing=("ingresado", "sum"), _ate=("atendido", "sum"), _saldo=("_saldo", "sum"))
        .sort_values([group_col, "anio"])
    )
    for src_col, prefix in (("_ing", "ingresado"), ("_ate", "atendido"), ("_saldo", "saldo")):
        yearly[f"hist_{prefix}_mean_prev"] = yearly.groupby(group_col)[src_col].transform(
            lambda s: s.expanding().mean().shift(1)
        )
    for src_col, prefix in (("_ing", "ingresado"), ("_ate", "atendido")):
        prev = yearly.groupby(group_col)[src_col].shift(1)
        yearly[f"growth_{prefix}_prev"] = (yearly[src_col] - prev) / prev.where(prev != 0, float("nan"))
    lag_cols = [c for c in yearly.columns if c.startswith("hist_") or c.startswith("growth_")]
    out = out.merge(yearly[[group_col, "anio"] + lag_cols], on=[group_col, "anio"], how="left")
    log(f"derived 14 columns (lags NaN on first district-year by construction)")
    return out


@register_stage
class FeatureEngineeringStage(Stage):
    name = "feature_engineering"
    seccion_paper = "3.3 Feature Engineering"
    output_dir = Path(OUTPUT_DIR, "tables").as_posix()
    manifest_filename = "feature_engineering_manifest.json"

    def is_done(self) -> bool:
        manifest = read_manifest(self.output_dir, self.manifest_filename)
        if not isinstance(manifest, dict):
            return False
        artifact = manifest.get("artifact_path", "")
        return bool(artifact) and Path(artifact).exists()

    def run(self) -> dict:
        log_path = new_run_log(self.name)
        ctx = resolve_context()
        log_line(log_path, f"context={ctx['context']} DATA_DIR={ctx['data_dir']} OUTPUT_DIR={ctx['output_dir']}")
        try:
            try:
                import pyarrow  # noqa: F401 — silver parquet IO
            except ImportError:
                raise RuntimeError("pyarrow is required: pip install -r requirements.txt")

            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            fe_cfg = cfg.get("feature_engineering") or {}
            if fe_cfg.get("derive") != "auto":
                raise ValueError("feature_engineering.derive must be auto")
            declared = [d.get("name") for d in (fe_cfg.get("derived") or []) if isinstance(d, dict)]
            group_col = fe_cfg.get("group_col", "distrito_fiscal")
            storage = cfg.get("storage") or {}
            silver_dir = get_data_dir() / storage.get("silver_dir", "silver")
            silver_dir.mkdir(parents=True, exist_ok=True)

            silver_src = load_upstream("consolidation", key="artifact_path")
            if not silver_src or not Path(silver_src).exists():
                raise RuntimeError("consolidation silver artifact missing — run consolidation first")
            df = pd.read_parquet(silver_src)
            log_line(log_path, f"loaded {silver_src} rows={len(df)}")
            print(f"[progress] engineering on {len(df)} rows", flush=True)

            df = _add_derived(df, group_col, lambda m: log_line(log_path, m))
            missing = [c for c in declared if c not in df.columns]
            if missing:
                raise RuntimeError(f"derived columns missing after build: {missing}")
            out_path = silver_dir / fe_cfg.get("output", "engineered.parquet")
            df.to_parquet(out_path, index=False)
            df.head(20).to_csv(Path(self.output_dir) / "feature_engineering_preview.csv", index=False, encoding="utf-8")

            manifest = {
                "stage": self.name,
                "derive": "auto",
                "n_derived": len(declared),
                "derived_names": declared,
                "artifact_path": out_path.as_posix(),
                "n_rows": int(len(df)),
                "source_of_truth": fe_cfg.get("source_of_truth", ""),
            }
            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok", "quality_check": {"passed": True, "failures": [], "placeholders": False}})
            log_line(log_path, f"[ok] wrote {out_path.as_posix()}")
            print(f"[progress] engineering done n_derived={len(declared)}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
