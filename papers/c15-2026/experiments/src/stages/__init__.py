# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Autoregistro de stages — import side-effects for @register_stage."""

# Import concrete stages so get_registry() sees all names (order = execution order for --stage all)
# Keep alphabetical import but registry insertion order matters for main.py iteration
from src.stages import consolidation  # noqa: F401
from src.stages import feature_engineering  # noqa: F401
from src.stages import preprocessing  # noqa: F401
from src.stages import feature_selection  # noqa: F401
from src.stages import split  # noqa: F401
from src.stages import train  # noqa: F401

