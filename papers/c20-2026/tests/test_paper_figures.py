# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 11 (paper figures) and its automatic QA, on synthetic data only.

Two halves. The QA must catch each fault it promises to catch: a point outside
the axes, a legend over the data, overlapping or cut-off text, a NaN, a figure
too tall, a missing glyph, a blank or badly cropped image. And the stage must
draw every figure end to end from a synthetic outputs/ (tests/figures_fixture.py)
and report a broken table instead of drawing past it. The map (Fig01) needs
cartopy and Natural Earth, which the test environment does not have; it is
exercised by the notebook's probe on Colab.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("PIL")

PAPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER / "experiments"))
sys.path.insert(0, str(PAPER / "tests"))

import _figqa as qa  # noqa: E402
import _figstyle as st  # noqa: E402

plt = st.setup()
NO_MAP = ["Fig02", "Fig03", "Fig04", "Fig05", "Fig06", "Fig07", "Fig08", "Fig09", "Fig10",
          "FigS1", "FigS2", "FigS3"]


def small_fig(width=st.SINGLE_MM, height=60):
    return st.figure(plt, width, height)


# --- QA: each check catches its fault ----------------------------------------------------------

def test_clipping_catches_a_point_outside_the_axes():
    fig, ax = small_fig()
    ax.plot([0, 1, 2], [0.1, 0.2, 0.9], "o")
    assert qa.check_clipping(fig) == []
    ax.set_ylim(0, 0.5)
    assert qa.check_clipping(fig) and "outside" in qa.check_clipping(fig)[0]
    plt.close(fig)


def test_clipping_reads_dates_as_dates():
    fig, ax = small_fig()
    ax.plot(pd.date_range("2023-01-01", periods=5, freq="W"), np.arange(5.0))
    assert qa.check_clipping(fig) == []
    plt.close(fig)


def test_legend_over_the_data_is_caught_and_outside_is_fine():
    fig, ax = small_fig()
    ax.plot(np.linspace(0, 1, 50), np.full(50, 0.95), "o", label="a series")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper center")
    assert qa.check_legend_overlap(fig)
    ax.get_legend().remove()
    fig.legend(loc="outside lower center")
    assert qa.check_legend_overlap(fig) == []
    plt.close(fig)


def test_overlapping_and_cut_texts_and_small_fonts_are_caught():
    fig, ax = small_fig()
    ax.text(0.5, 0.5, "first label", transform=ax.transAxes)
    ax.text(0.51, 0.5, "second label", transform=ax.transAxes)
    probs = qa.check_text(fig)
    assert any("overlap" in p for p in probs)
    plt.close(fig)
    fig, ax = small_fig()
    ax.text(1.3, 0.5, "far outside the canvas", transform=ax.transAxes)
    ax.text(0.1, 0.1, "tiny", fontsize=4, transform=ax.transAxes)
    probs = qa.check_text(fig)
    assert any("cut at the figure edge" in p for p in probs)
    assert any("< 6" in p for p in probs)
    plt.close(fig)


def test_an_annotation_arrow_is_not_text():
    """Callout lines may cross other labels; only the label text must not."""
    fig, ax = small_fig()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.annotate("upper label", xy=(9, 1), xytext=(1, 7), arrowprops={"arrowstyle": "-"})
    ax.annotate("lower label", xy=(9, 8), xytext=(1, 3), arrowprops={"arrowstyle": "-"})
    assert qa.check_text(fig) == []
    plt.close(fig)


def test_tick_labels_outside_the_view_do_not_count():
    fig, ax = small_fig()
    ax.plot([0, 1], [0, 1])
    ax.set_xticks([-5, 0, 0.5, 1, 6])
    ax.set_xlim(0, 1)
    assert qa.check_text(fig) == []
    plt.close(fig)


def test_size_limits():
    fig, _ = small_fig(st.DOUBLE_MM, 120)
    probs = qa.check_size(fig, st.DOUBLE_MM, st.MAX_HEIGHT_MM["diagram"])
    assert any("exceeds" in p for p in probs)
    assert qa.check_size(fig, st.SINGLE_MM, 200) and "width" in qa.check_size(fig, st.SINGLE_MM, 200)[0]
    plt.close(fig)


def test_data_checks():
    df = pd.DataFrame({"v": [0.1, np.nan, np.inf]})
    assert "2 non-finite" in qa.check_finite(df, ["v"])[0]
    assert qa.check_count(df, 3, "rows") == [] and qa.check_count(df, 4, "rows")
    a = pd.DataFrame({"h": ["W1", "W2"], "x": [0.30, 0.40]})
    b = pd.DataFrame({"h": ["W1", "W2"], "x": [0.30, 0.47]})
    assert qa.check_agree(a, a, ["h"], "x", "x", 1e-9, "same") == []
    assert "disagree" in qa.check_agree(a, b, ["h"], "x", "x", 1e-3, "diff")[0]


def test_drawn_values_are_found_on_the_canvas():
    fig, ax = small_fig()
    ax.errorbar([0, 1], [0.2, 0.3], yerr=0.05, fmt="o")
    ax.bar([2], [0.7])
    assert qa.check_drawn(fig, [0.2, 0.3, 0.7]) == []
    assert qa.check_drawn(fig, [0.2, 0.55])
    plt.close(fig)


def test_missing_glyph_warnings_become_problems():
    class W:
        message = "Glyph 8322 (\\N{SUBSCRIPT TWO}) missing from font(s) Arial."
    assert qa.check_glyphs([W()]) and qa.check_glyphs([]) == []


def test_image_checks_blank_and_margins(tmp_path):
    from PIL import Image
    blank = tmp_path / "blank.png"
    Image.new("RGB", (600, 300), "white").save(blank, dpi=(300, 300))
    assert any("blank" in p for p in qa.check_image(blank))
    lowdpi = tmp_path / "low.png"
    im = Image.new("RGB", (600, 300), "white")
    im.paste((0, 0, 0), (0, 0, 600, 300))
    im.save(lowdpi, dpi=(72, 72))
    assert any("dpi" in p for p in qa.check_image(lowdpi))
    margin = tmp_path / "margin.png"
    im = Image.new("RGB", (600, 300), "white")
    im.paste((0, 0, 0), (0, 0, 300, 300))                # right half empty
    im.save(margin, dpi=(300, 300))
    assert any("right" in p for p in qa.check_image(margin))


def test_cvd_and_grayscale_versions(tmp_path):
    from PIL import Image
    src = tmp_path / "c.png"
    Image.new("RGB", (40, 20), (213, 94, 0)).save(src, dpi=(300, 300))
    cvd, gray = qa.simulate_cvd(src, tmp_path / "d.png"), qa.grayscale(src, tmp_path / "g.png")
    with Image.open(cvd) as a, Image.open(gray) as b:
        assert a.size == (40, 20) and b.mode == "L"


def test_spread_separates_a_dense_cluster_exactly():
    lats = [-11.8, -12.4, -15.9, -16.6, -17.3]          # the five stations, map callouts
    ys = sorted(st.spread(lats, 2.0))
    assert all(b - a >= 2.0 - 1e-9 for a, b in zip(ys, ys[1:]))
    assert abs(np.mean(ys) - np.mean(lats)) < 1e-9


def test_spread_keeps_order_and_gap():
    ys = st.spread([0.30, 0.31, 0.305, 0.9], 0.05)
    order = np.argsort([0.30, 0.31, 0.305, 0.9])
    assert list(np.argsort(ys)) == list(order)
    s = sorted(ys)
    assert all(b - a >= 0.05 - 1e-9 for a, b in zip(s, s[1:]))


# --- the stage end to end ------------------------------------------------------------------------

def run_stage(root: Path, only: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "OUTPUT_DIR": str(root / "outputs"), "DATA_DIR": str(root / "data"),
           "MPLBACKEND": "Agg"}
    return subprocess.run([sys.executable, str(PAPER / "experiments" / "11_paper_figures.py"),
                           "--only", *only], cwd=PAPER / "experiments", env=env,
                          capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    import figures_fixture
    root = figures_fixture.write(tmp_path_factory.mktemp("figs"))
    only = NO_MAP if _has_dot() else [f for f in NO_MAP if f != "Fig02"]
    return root, run_stage(root, only), only


def _has_dot() -> bool:
    import shutil
    try:
        import graphviz  # noqa: F401
    except ImportError:
        return False
    return shutil.which("dot") is not None


def test_every_figure_is_drawn_and_passes_qa(drawn):
    root, proc, only = drawn
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    out = root / "outputs" / "figures" / "paper"
    report = json.loads((out / "qa.json").read_text(encoding="utf-8"))
    assert report["failed"] == []
    assert len(report["figures"]) == len(only)
    for name, entry in report["figures"].items():
        for ext in ("png", "pdf", "csv"):
            assert (out / f"{name}.{ext}").is_file(), (name, ext)
        assert (out / "qa" / f"{name}_deuteranopia.png").is_file()
        assert (out / "qa" / f"{name}_grayscale.png").is_file()
    assert (out / "contact_sheet.png").is_file() and (out / "qa.md").is_file()


def test_a_broken_table_fails_the_stage_and_names_the_figure(tmp_path):
    import figures_fixture
    root = figures_fixture.write(tmp_path)
    t16 = root / "outputs" / "tables" / "T16_hybrid_cfs.csv"
    d = pd.read_csv(t16)
    d.loc[d["system"] == "Ensemble", "CRPSS_clim"] += 0.05   # 09 and 09f now disagree
    d.to_csv(t16, index=False)
    proc = run_stage(root, ["Fig04"])
    assert proc.returncode == 1
    report = json.loads((root / "outputs" / "figures" / "paper" / "qa.json").read_text("utf-8"))
    assert report["failed"] == ["Fig04_blind_skill"]
    assert any("T2 vs T16" in p for p in report["figures"]["Fig04_blind_skill"]["problems"])
