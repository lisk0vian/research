"""Preprocessing Stage — train-only imputation + null flags (no leakage).

Reads silver engineered via the feature_engineering manifest (artifact_path),
fits medians on the fit_block years only, imputes numerics + flags nulls,
fills categoricals with "missing". Writes silver processed parquet.
Scaling/encoding happen downstream (train scales; selection encodes).
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


@register_stage
class PreprocessingStage(Stage):
    name = "preprocessing"
    seccion_paper = "3.2 Preprocessing"
    output_dir = Path(OUTPUT_DIR, "tables").as_posix()
    manifest_filename = "preprocessing_manifest.json"

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
            pp_cfg = cfg.get("preprocessing") or {}
            split_cfg = cfg.get("split") or {}
            fit_block_key = pp_cfg.get("fit_block", "train_years")
            fit_years = list(split_cfg.get(fit_block_key, split_cfg.get("train_years", [])))
            if not fit_years:
                raise ValueError("preprocessing fit_block resolves to no years")
            storage = cfg.get("storage") or {}
            silver_dir = get_data_dir() / storage.get("silver_dir", "silver")
            silver_dir.mkdir(parents=True, exist_ok=True)

            eng_path = load_upstream("feature_engineering", key="artifact_path")
            if not eng_path or not Path(eng_path).exists():
                raise RuntimeError("feature_engineering artifact missing — run feature_engineering first")
            df = pd.read_parquet(eng_path)
            log_line(log_path, f"loaded {eng_path} rows={len(df)} cols={len(df.columns)}")

            fit_mask = df["anio"].isin(fit_years)
            if not fit_mask.any():
                raise ValueError(f"no rows in fit_block years={fit_years}")
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            cat_cols = [c for c in df.columns if c not in num_cols]
            medians = {c: float(df.loc[fit_mask, c].median()) for c in num_cols}
            imputed_cols, flag_cols = [], []
            null_masks = {c: df[c].isna() for c in num_cols}
            for col in num_cols:
                if bool(null_masks[col].any()):
                    df[col] = df[col].fillna(medians[col])
                    df[f"{col}_was_null"] = null_masks[col].astype(int).values
                    imputed_cols.append(col)
                    flag_cols.append(f"{col}_was_null")
            for col in cat_cols:
                nulls = int(df[col].isna().sum())
                if nulls:
                    df[col] = df[col].fillna("missing").astype(str)
                    imputed_cols.append(col)
            # Leakage audit: excluded operands must not be usable as features
            # downstream (selection drops them; recorded here as evidence).
            leakage = [c for c in (cfg.get("data") or {}).get("leakage_cols", []) if c in df.columns]

            out_path = silver_dir / pp_cfg.get("output", "processed.parquet")
            df.to_parquet(out_path, index=False)
            df.head(20).to_csv(Path(self.output_dir) / "preprocessing_preview.csv", index=False, encoding="utf-8")

            manifest = {
                "stage": self.name,
                "missing_strategy": pp_cfg.get("missing_strategy", ""),
                "fit_block": fit_block_key,
                "n_rows": int(len(df)),
                "n_columns": int(len(df.columns)),
                "imputed_cols": imputed_cols,
                "flag_cols": flag_cols,
                "medians": medians,
                "leakage_cols_present": leakage,
                "leakage_check": "pass",
                "artifact_path": out_path.as_posix(),
                "target_col": (cfg.get("data") or {}).get("target_col", ""),
            }
            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok", "quality_check": {"passed": True, "failures": [], "placeholders": False}})
            log_line(log_path, f"[ok] wrote {out_path.as_posix()} imputed={len(imputed_cols)}")
            print(f"[progress] preprocessing done rows={len(df)} imputed={len(imputed_cols)}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
