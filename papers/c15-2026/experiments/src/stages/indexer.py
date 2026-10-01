import json
import os
from pathlib import Path


def actualizar_indice(name, seccion, output_dir, manifest):
    """Keep outputs/manifest_index.json as single source of truth.

    Args:
        name: stage name (unique key).
        seccion: paper section this stage contributes to.
        output_dir: directory where the stage writes its outputs.
        manifest: dict returned by Stage.run().

    Index shape (canonical, dict-rich):
        {<stage>: {"seccion_paper": str, "output_dir": str (posix), "manifest": dict}}
    If the stage already existed, replace the entry (no duplicates).
    Migrates legacy list format [{stage, seccion_paper, path, keys_principales}]
    preserving seccion/output_dir and stashing old keys under
    manifest._migrated_keys.
    """
    # OUTPUT_DIR is read at runtime to respect os.environ override in Colab
    output_base = os.environ.get("OUTPUT_DIR", "../outputs")
    index_path = Path(output_base) / "manifest_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Migrate legacy list format to canonical dict
                    migrated = {}
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("stage")
                        if not key:
                            continue
                        old_path = item.get("path", "")
                        migrated[key] = {
                            "seccion_paper": item.get("seccion_paper", ""),
                            "output_dir": Path(old_path).as_posix() if old_path else "",
                            "manifest": {"_migrated_keys": item.get("keys_principales", [])},
                        }
                    data = migrated
                elif not isinstance(data, dict):
                    data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    safe_manifest = manifest if isinstance(manifest, dict) else {"_non_dict_manifest": []}

    entry = {
        "seccion_paper": seccion,
        "output_dir": Path(output_dir).as_posix(),
        "manifest": safe_manifest,
    }

    # Replace if it already existed, do not duplicate
    data[name] = entry

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
