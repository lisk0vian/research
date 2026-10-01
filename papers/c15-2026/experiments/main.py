import argparse

# Carga .env primero para que src.paths vea GDRIVE_* y DATA_DIR/OUTPUT_DIR
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import src.stages  # noqa: F401 — importa para que se autoregistren todas las stages
from src.stages.indexer import actualizar_indice
from src.stages.registry import get_registry


def main():
    parser = argparse.ArgumentParser(description="Orquestador de pipeline de investigación ML")
    parser.add_argument("--stage", default="all", help='Stage a ejecutar: "all" o <name>')
    parser.add_argument("--force", action="store_true", help="Recompute even when is_done() is True (single stage only, no cascade)")
    args = parser.parse_args()

    registry = get_registry()

    if args.stage == "all":
        stages_to_run = list(registry.items())
    else:
        if args.stage not in registry:
            available = list(registry.keys())
            print(f"[error] Stage '{args.stage}' no encontrada. Disponibles: {available}")
            return
        stages_to_run = [(args.stage, registry[args.stage])]

    if not stages_to_run:
        print("[info] No hay stages registradas. Nada que ejecutar.")
        return

    for name, stage_cls in stages_to_run:
        stage = stage_cls()
        if stage.is_done() and not (args.force and args.stage != "all"):
            print(f"[skip] Stage '{name}' ya completada (is_done=True, manifest valid).")
            print(f"[skip] Re-run with: !python main.py --stage {name} --force (ignores is_done, no cascade).")
            continue
        if args.force and args.stage != "all":
            # Propagate to per-model resume inside the stage (e.g. train skips
            # finished models otherwise, and --force would silently reuse them).
            import os

            os.environ["STAGE_FORCE"] = "1"
            print(f"[force] Recomputing stage '{name}' (per-model resume disabled).")

        print(f"[run] Ejecutando stage '{name}'...")
        try:
            manifest = stage.run()
        except Exception as e:
            print(f"[error] Stage '{name}' failed: {e} — see OUTPUT_DIR/logs/run_{name}_*.log and errors.json")
            raise

        actualizar_indice(
            name=stage.name,
            seccion=stage.seccion_paper,
            output_dir=stage.output_dir,
            manifest=manifest,
        )
        print(f"[ok] Stage '{name}' completada.")


if __name__ == "__main__":
    main()
