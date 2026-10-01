"""Split Stage — temporal year-block gold matrices from the shared encoding.

Method (declared in config.yaml, never fixed counts):
- Reads processed via the preprocessing manifest and the selection result
  (selected_features plus encoding lists) via the feature_selection manifest.
- Recomputes the encoding with the exact same rule as feature_selection
  (one-hot when train nunique <= one_hot_max_cardinality, else frequency,
  fit on train_full) and rebuilds the proxy target via _io.build_target, so
  thresholds match train by construction.
- Writes gold/X_<split>.parquet (selected encoded columns, float) plus
  gold/y_<split>.parquet (single target column) for the temporal blocks, the
  split_index.json registry, and the split_map.csv audit table.
"""
import traceback
from pathlib import Path

import yaml

from src.paths import OUTPUT_DIR
from src.stages._io import (
    append_errors_entry,
    apply_encoding,
    build_target,
    fit_encoding_maps,
    get_data_dir,
    load_upstream,
    log_line,
    new_run_log,
    read_manifest,
    resolve_context,
    write_manifest_atomic,
)
from src.stages.base import Stage
from src.stages.registry import register_stage


# NOTE: encoding rule lives in src.stages._io (fit_encoding_maps /
# apply_encoding) as the single source of truth shared with
# feature_selection.py.


def _write_parquet_atomic(frame, target) -> None:
    """Write a parquet file via tmp plus rename (crash-safe for dropped tabs)."""
    target = Path(target)
    tmp = target.with_suffix(".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(target)


@register_stage
class SplitStage(Stage):
    name = "split"
    seccion_paper = "3.5 Temporal Split"
    output_dir = Path(OUTPUT_DIR, "tables").as_posix()
    manifest_filename = "split_manifest.json"
    map_filename = "split_map.csv"

    def is_done(self) -> bool:
        """Done only when our manifest is valid and every gold path exists."""
        manifest = read_manifest(self.output_dir, self.manifest_filename)
        if not isinstance(manifest, dict):
            return False
        feature_list = manifest.get("feature_list")
        splits = manifest.get("splits")
        gold_paths = manifest.get("gold_paths")
        if not isinstance(feature_list, list) or not feature_list:
            return False
        if not isinstance(splits, dict) or not splits:
            return False
        if not isinstance(gold_paths, dict) or not gold_paths:
            return False
        for path_value in gold_paths.values():
            if not isinstance(path_value, str) or not Path(path_value).exists():
                return False
        return True

    def run(self) -> dict:
        """Recompute encoding plus target, write gold matrices, index, and map."""
        log_path = new_run_log(self.name)
        ctx = resolve_context()
        log_line(log_path, f"context={ctx['context']} DATA_DIR={ctx['data_dir']} OUTPUT_DIR={ctx['output_dir']}")
        try:
            import numpy as np
            import pandas as pd

            try:
                import pyarrow  # noqa: F401 — gold parquet IO
            except ImportError as exc:
                raise RuntimeError("pyarrow is required: pip install -r requirements.txt") from exc

            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            with open(cfg_path, encoding="utf-8") as handle:
                cfg = yaml.safe_load(handle)
            data_cfg = cfg.get("data") or {}
            split_cfg = cfg.get("split") or {}
            fs_cfg = cfg.get("feature_selection") or {}
            storage = cfg.get("storage") or {}

            target_col = str(data_cfg.get("target_col", "riesgo_congestion"))
            exclude_set = set(data_cfg.get("exclude_cols") or [])
            fs_years = [int(y) for y in (split_cfg.get("feature_selection_years") or [])]
            fs_valid_year = int(split_cfg.get("feature_selection_valid_year"))
            train_years = [int(y) for y in (split_cfg.get("train_years") or [])]
            calib_year = int(split_cfg.get("calib_valid_year"))
            test_year = int(split_cfg.get("test_year"))
            external_year = int(split_cfg.get("external_year"))
            method = str(split_cfg.get("method", "temporal"))
            if method != "temporal":
                raise ValueError(f"split.method={method!r} unsupported (only 'temporal')")
            max_card = int((fs_cfg.get("encoding") or {})["one_hot_max_cardinality"])
            gold_dir = get_data_dir() / str(storage.get("gold_dir", "gold"))
            gold_dir.mkdir(parents=True, exist_ok=True)
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            processed_path = load_upstream("preprocessing", key="artifact_path")
            selected_features = load_upstream("feature_selection", key="selected_features")
            encoding_info = load_upstream("feature_selection", key="encoding")
            if not isinstance(selected_features, list) or not selected_features:
                raise RuntimeError("feature_selection manifest has no selected_features — re-run it first (main.py --stage feature_selection)")
            if not isinstance(encoding_info, dict):
                raise RuntimeError("feature_selection manifest has no encoding block — re-run it first (main.py --stage feature_selection)")
            log_line(log_path, f"selection gives {len(selected_features)} features")
            print(f"[progress] split loading {processed_path}", flush=True)
            df = pd.read_parquet(processed_path)
            log_line(log_path, f"loaded rows={len(df)} cols={len(df.columns)}")

            # Same proxy target as train and feature_selection: thresholds come
            # exclusively from the train_years block by construction.
            frame, y_all, q75_s, q25_t, train_prev = build_target(df, train_years, target_col)
            frame = frame.reset_index(drop=True)
            y_all_np = np.asarray(y_all).ravel()
            log_line(log_path, f"target q75_s={q75_s:.4f} q25_t={q25_t:.4f} train_prevalence={train_prev:.4f} (reference only)")
            print(f"[progress] target built q75_s={q75_s:.4f} q25_t={q25_t:.4f}", flush=True)

            # Recompute the encoding on the EXACT fitted column lists from the
            # selection manifest (survivors only) and verify the resulting
            # one-hot/frequency sets match before writing any gold file.
            fitted_num = list(encoding_info.get("fitted_num_cols") or [])
            fitted_cat = list(encoding_info.get("fitted_cat_cols") or [])
            if not fitted_num and not fitted_cat:
                raise RuntimeError("feature_selection manifest lacks fitted column lists — re-run it first (main.py --stage feature_selection)")
            num_cols = [c for c in fitted_num if c in frame.columns]
            cat_cols = [c for c in fitted_cat if c in frame.columns]
            if len(num_cols) != len(fitted_num) or len(cat_cols) != len(fitted_cat):
                raise RuntimeError("processed table lost fitted columns — re-run feature_engineering/preprocessing first")
            train_full_series = frame["anio"].isin(train_years)
            if not bool(train_full_series.any()):
                raise ValueError(f"no rows in train_years={train_years}")
            one_hot_cols, one_hot_cats, freq_cols, freq_maps = fit_encoding_maps(
                frame, cat_cols, train_full_series, max_card
            )
            if set(one_hot_cols) != set(encoding_info.get("one_hot_cols") or []):
                raise RuntimeError("recomputed one-hot columns differ from the feature_selection manifest — re-run feature_selection first")
            if set(freq_cols) != set(encoding_info.get("frequency_cols") or []):
                raise RuntimeError("recomputed frequency columns differ from the feature_selection manifest — re-run it first")
            for col in one_hot_cols:
                if [str(v) for v in one_hot_cats[col]] != [str(v) for v in (encoding_info.get("one_hot_categories") or {}).get(col, [])]:
                    raise RuntimeError(f"one-hot vocabulary drifted for '{col}' — re-run feature_selection first")
            encoded_all = apply_encoding(frame, num_cols, one_hot_cols, one_hot_cats, freq_cols, freq_maps)
            missing_selected = [c for c in selected_features if c not in encoded_all.columns]
            if missing_selected:
                raise RuntimeError(f"selected features missing after re-encoding {missing_selected[:5]} — re-run feature_selection first")
            log_line(log_path, f"encoding verified n_encoded={encoded_all.shape[1]} selected={len(selected_features)}")
            print(f"[progress] encoding verified selected={len(selected_features)}", flush=True)

            fit_years = [y for y in train_years if y != fs_valid_year]
            if not fit_years:
                raise ValueError("search_train is empty: feature_selection_valid_year covers all of train_years")
            split_years = {
                "search_train": fit_years,
                "search_valid": [fs_valid_year],
                "train_full": list(train_years),
                "calib": [calib_year],
                "test": [test_year],
                "external": [external_year],
            }

            splits_detail = {}
            gold_paths = {}
            map_rows = []
            for split_name, years in split_years.items():
                block_series = frame["anio"].isin(years)
                if not bool(block_series.any()):
                    raise ValueError(f"empty block '{split_name}' for years={years}: check split years vs anio values")
                x_block = encoded_all.loc[block_series, selected_features].astype(float)
                y_block = y_all_np[block_series.to_numpy()].astype(int)
                x_path = gold_dir / f"X_{split_name}.parquet"
                y_path = gold_dir / f"y_{split_name}.parquet"
                _write_parquet_atomic(x_block, x_path)
                _write_parquet_atomic(
                    pd.DataFrame({"anio": frame.loc[block_series, "anio"].to_numpy(dtype=int), target_col: y_block}),
                    y_path,
                )
                prevalence = float(y_block.mean()) if len(y_block) else 0.0
                splits_detail[split_name] = {
                    "years": [int(y) for y in years],
                    "n_rows": int(len(y_block)),
                    "prevalence": prevalence,
                }
                gold_paths[f"X_{split_name}"] = x_path.as_posix()
                gold_paths[f"y_{split_name}"] = y_path.as_posix()
                for year in years:
                    map_rows.append({"anio": int(year), "split": split_name})
                log_line(log_path, f"block {split_name} years={years} rows={len(y_block)} prevalence={prevalence:.4f}")
                print(f"[progress] block {split_name} rows={len(y_block)} prevalence={prevalence:.4f}", flush=True)

            split_index = {
                "splits": splits_detail,
                "thresholds": {"q75_s": float(q75_s), "q25_t": float(q25_t)},
                "feature_list": list(selected_features),
                "target": target_col,
            }
            index_path = write_manifest_atomic(gold_dir.as_posix(), "split_index.json", split_index)
            gold_paths["split_index"] = index_path.as_posix()
            log_line(log_path, f"[ok] wrote {index_path.as_posix()}")

            map_path = Path(self.output_dir) / self.map_filename
            map_tmp = map_path.with_suffix(".tmp")
            pd.DataFrame(map_rows, columns=["anio", "split"]).to_csv(map_tmp, index=False, encoding="utf-8")
            map_tmp.replace(map_path)
            log_line(log_path, f"[ok] wrote {map_path.as_posix()} rows={len(map_rows)}")

            manifest = {
                "stage": self.name,
                "method": method,
                "feature_selection_years": fs_years,
                "feature_selection_valid_year": fs_valid_year,
                "train_years": train_years,
                "calib_valid_year": calib_year,
                "test_year": test_year,
                "external_year": external_year,
                "thresholds": {"q75_s": float(q75_s), "q25_t": float(q25_t)},
                "splits": splits_detail,
                "feature_list": list(selected_features),
                "gold_paths": gold_paths,
                "split_map": map_path.as_posix(),
            }
            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok"})
            log_line(log_path, "[ok] stage completed")
            print(f"[progress] split done blocks={len(splits_detail)} features={len(selected_features)}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
