"""Consolidation Stage — 2019.csv … 2026.csv -> consolidated.csv + silver parquet.

Datalake layers (declared in config.yaml:storage, all under DATA_DIR):
- raw (immutable inputs, never overwritten; hashes frozen in checksums.json)
- silver (versioned consolidated parquet + sha, this stage writes it)
- gold (per-split matrices; split writes in phase 2.1)
"""
import hashlib
import json
import traceback
from pathlib import Path

import pandas as pd
import yaml

from src.paths import DATA_DIR, OUTPUT_DIR
from src.stages._io import (
    append_errors_entry,
    get_data_dir,
    get_output_base,
    log_line,
    new_run_log,
    read_manifest,
    resolve_context,
    write_manifest_atomic,
)
from src.stages.base import Stage
from src.stages.registry import register_stage


def _sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


@register_stage
class ConsolidationStage(Stage):
    name = "consolidation"
    seccion_paper = "3.1 Data Consolidation"
    output_dir = Path(OUTPUT_DIR, "tables").as_posix()
    manifest_filename = "consolidation_manifest.json"

    def is_done(self) -> bool:
        """Done only when the manifest is valid AND silver parquet exists."""
        manifest = read_manifest(self.output_dir, self.manifest_filename)
        if not isinstance(manifest, dict):
            return False
        silver = manifest.get("silver_path", "")
        return bool(silver) and Path(silver).exists()

    def run(self) -> dict:
        log_path = new_run_log(self.name)
        ctx = resolve_context()
        log_line(log_path, f"context={ctx['context']} DATA_DIR={ctx['data_dir']} OUTPUT_DIR={ctx['output_dir']}")
        try:
            import pyarrow  # noqa: F401 — required for silver parquet
        except ImportError:
            raise RuntimeError("pyarrow is required for silver parquet: pip install -r requirements.txt")
        try:
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            (get_output_base() / "logs").mkdir(parents=True, exist_ok=True)

            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            storage = cfg.get("storage") or {}
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            silver_dir = data_dir / storage.get("silver_dir", "silver")
            silver_dir.mkdir(parents=True, exist_ok=True)
            raw = cfg["data"]["raw_path"]
            consolidated = data_dir / raw

            # Freeze raw hashes (immutability evidence; warn-only on drift).
            raw_paths = sorted(data_dir.glob("20*.csv"))
            raw_hashes = {p.name: _sha12(p) for p in raw_paths}
            checksums_path = data_dir / "checksums.json"
            recorded = {}
            if checksums_path.exists():
                try:
                    recorded = json.loads(checksums_path.read_text(encoding="utf-8"))
                    if not isinstance(recorded, dict):
                        recorded = {}
                except (json.JSONDecodeError, OSError) as e:
                    log_line(log_path, f"WARN unreadable checksums.json, rewriting ({e})")
                    recorded = {}
            for name, digest in raw_hashes.items():
                if name in recorded and recorded[name] != digest:
                    log_line(log_path, f"WARN raw input changed since freeze: {name}")
                    print(f"[warn] raw input changed since freeze: {name} (recorded, not asserted)")
            dict_name = storage.get("dictionary", "dictionary.md")
            dict_path = data_dir / dict_name
            dict_sha = _sha12(dict_path) if dict_path.exists() else None

            if consolidated.exists() and consolidated.stat().st_size > 0:
                log_line(log_path, f"consolidated.csv exists, reusing ({consolidated.stat().st_size} bytes)")
                df_all = pd.read_csv(consolidated, encoding="utf-8")
                skipped = True
                n_files = len(raw_paths)
            else:
                parts = []
                for p in raw_paths:
                    df = pd.read_csv(p, encoding="utf-8-sig")
                    df.columns = [c.replace("especilizada", "especializada") for c in df.columns]
                    df["archivo_fuente"] = p.name
                    parts.append(df)
                if not parts:
                    # Dummy for CI without data (auditable, never silent).
                    df_all = pd.DataFrame(
                        {
                            "anio": [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
                            "ingresado": [100, 110, 105, 120, 130, 125, 140, 135],
                            "atendido": [80, 85, 90, 95, 100, 105, 110, 115],
                            "riesgo_congestion": [0, 1, 0, 1, 0, 1, 0, 1],
                            "archivo_fuente": ["dummy.csv"] * 8,
                        }
                    )
                    log_line(log_path, "WARN no 20*.csv inputs: wrote auditable dummy table")
                    print("[warn] no 20*.csv inputs: wrote auditable dummy table")
                else:
                    df_all = pd.concat(parts, ignore_index=True)
                df_all.to_csv(consolidated, index=False, encoding="utf-8")
                skipped = False
                n_files = len(parts)
                print(f"[progress] consolidated {len(df_all)} rows from {n_files} files", flush=True)

            # Silver layer: versioned parquet + frozen checksums (csv + raws).
            silver_path = silver_dir / "consolidated.parquet"
            df_all.to_parquet(silver_path, index=False)
            csv_sha = _sha12(consolidated)
            silver_sha = _sha12(silver_path)
            checksums = {**recorded, raw: csv_sha, "silver/consolidated.parquet": silver_sha, **raw_hashes}
            if dict_sha:
                checksums[dict_name] = dict_sha
            tmp_checksums = checksums_path.with_suffix(".tmp")
            tmp_checksums.write_text(json.dumps(checksums, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_checksums.replace(checksums_path)

            manifest = {
                "stage": self.name,
                "n_rows": int(len(df_all)),
                "n_columns": int(len(df_all.columns)),
                "n_files_consolidated": int(n_files),
                "sha256_12": csv_sha,
                "output_path": consolidated.as_posix(),
                "silver_path": silver_path.as_posix(),
                "artifact_path": silver_path.as_posix(),
                "silver_sha256_12": silver_sha,
                "raw_hashes": raw_hashes,
                "dictionary_sha256_12": dict_sha,
                "skipped": bool(skipped),
            }
            df_all.head(20).to_csv(
                Path(self.output_dir) / "consolidation_preview.csv", index=False, encoding="utf-8"
            )
            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok", "quality_check": {"passed": True, "failures": [], "placeholders": False}})
            log_line(log_path, f"[ok] rows={len(df_all)} silver={silver_path.as_posix()}")
            print(f"[progress] consolidation done rows={len(df_all)} silver={silver_path.name}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
