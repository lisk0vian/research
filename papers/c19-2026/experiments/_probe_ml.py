# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Probe for cell 2: the monotonic constraint must exist in this scikit-learn.

Plan v6 (B) depends on `monotonic_cst` in HistGradientBoostingClassifier.
This runs in seconds and fails hard before the pipeline if it is missing.
"""

import inspect

import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier

params = inspect.signature(HistGradientBoostingClassifier.__init__).parameters
assert "monotonic_cst" in params, "this scikit-learn lacks monotonic_cst"
print(f"sklearn {sklearn.__version__}: HistGradientBoosting monotonic_cst available")
