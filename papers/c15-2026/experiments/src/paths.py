# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
import os

# Carga .env (GDRIVE_FOLDER_ID etc.) sin fallar si no existe
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DATA_DIR = os.environ.get("DATA_DIR", "../data")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "../outputs")

# Drive IDs centralizados via .env (no hardcodear en AGENTS.md)
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")
GDRIVE_NOTEBOOK_ID = os.environ.get("GDRIVE_NOTEBOOK_ID", "")
GDRIVE_NOTEBOOK_NAME = os.environ.get("GDRIVE_NOTEBOOK_NAME", "experiments.ipynb")
GDRIVE_PROJECT_ID = os.environ.get("GDRIVE_PROJECT_ID", "c15-2026-experiments")
