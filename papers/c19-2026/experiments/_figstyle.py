# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Figure styling helpers for c19-2026."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def apply_style():
    plt.rcParams.update({
        'figure.dpi': 120,
        'font.size': 10,
        'axes.titlesize': 11,
    })

apply_style()
