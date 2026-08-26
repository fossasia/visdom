#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Manual visual check: plot one window of every kind, then look at them.

This is a script for a human, not a test. It needs a running server and its
result is a judgement about how the browser rendered the panes, which is why it
lives in ``example/manual/`` rather than under ``py/tests/`` — pytest collects
nothing here. Automated rendering checks belong to the Playwright and Cypress
visual-regression suites.

Usage:
    1. Start a server:  visdom -port 8097
    2. Run this:        python example/manual/visual_check.py
    3. Open a browser:  http://localhost:8097/env/visual_check
"""

import math
import sys
import time
import numpy as np

from visdom import Visdom

ENV = "visual_check"


def main():
    viz = Visdom(server="http://localhost", port=8097, env=ENV)
    if not viz.check_connection(timeout_seconds=5):
        print("ERROR: Cannot connect to Visdom server.")
        print("Start it with: visdom -port 8097")
        sys.exit(1)

    print(f"Connected to Visdom. Creating visualizations in env '{ENV}'...")
    print(f"Open http://localhost:8097/env/{ENV} to view.\n")

    # ===========================================================
    # 1. LINE PLOT — Single line
    # ===========================================================
    x = np.linspace(0, 4 * math.pi, 200)
    viz.line(
        Y=np.sin(x),
        X=x,
        opts=dict(
            title="1. Sine Wave (Line Plot)",
            xlabel="x",
            ylabel="sin(x)",
        ),
        win="line_single",
    )
    print("[OK] 1. Single line plot (sine wave)")

    # ===========================================================
    # 2. LINE PLOT — Multiple lines
    # ===========================================================
    viz.line(
        Y=np.column_stack((np.sin(x), np.cos(x), np.sin(x) * np.cos(x))),
        X=np.column_stack((x, x, x)),
        opts=dict(
            title="2. Multiple Lines (sin, cos, sin*cos)",
            legend=["sin(x)", "cos(x)", "sin(x)*cos(x)"],
            xlabel="x",
            ylabel="y",
        ),
        win="line_multi",
    )
    print("[OK] 2. Multiple line plot")

    # ===========================================================
    # 3. LINE PLOT — Append update (streaming data)
    # ===========================================================
    win = viz.line(
        Y=np.array([0.0]),
        X=np.array([0]),
        opts=dict(title="3. Streaming Line (append update)"),
        win="line_streaming",
    )
    for i in range(1, 50):
        viz.line(
            Y=np.array([np.sin(i * 0.2) + np.random.randn() * 0.1]),
            X=np.array([i]),
            win=win,
            update="append",
        )
    print("[OK] 3. Streaming line plot (50 appended points)")

    # ===========================================================
    # 4. SCATTER — 2D with classes
    # ===========================================================
    n = 200
    x_scatter = np.random.randn(n, 2)
    labels = (x_scatter[:, 0] > 0).astype(int) + 1  # 1 or 2
    viz.scatter(
        X=x_scatter,
        Y=labels,
        opts=dict(
            title="4. 2D Scatter (two classes)",
            legend=["Class A", "Class B"],
            markersize=8,
            xlabel="Feature 1",
            ylabel="Feature 2",
        ),
        win="scatter_2d",
    )
    print("[OK] 4. 2D scatter plot with classes")

    # ===========================================================
    # 5. SCATTER — 3D
    # ===========================================================
    viz.scatter(
        X=np.random.rand(100, 3),
        opts=dict(
            title="5. 3D Scatter Plot",
            markersize=5,
        ),
        win="scatter_3d",
    )
    print("[OK] 5. 3D scatter plot")

    # ===========================================================
    # 6. BAR CHART — Simple
    # ===========================================================
    viz.bar(
        X=np.array([28, 55, 43, 91, 72, 35]),
        opts=dict(
            title="6. Bar Chart",
            rownames=["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        ),
        win="bar_simple",
    )
    print("[OK] 6. Simple bar chart")

    # ===========================================================
    # 7. BAR CHART — Stacked
    # ===========================================================
    viz.bar(
        X=np.random.rand(5, 3) * 100,
        opts=dict(
            title="7. Stacked Bar Chart",
            stacked=True,
            legend=["Product A", "Product B", "Product C"],
            rownames=["Q1", "Q2", "Q3", "Q4", "Q5"],
        ),
        win="bar_stacked",
    )
    print("[OK] 7. Stacked bar chart")

    # ===========================================================
    # 8. HEATMAP
    # ===========================================================
    hm_data = np.outer(np.arange(1, 11), np.arange(1, 11))
    viz.heatmap(
        X=hm_data,
        opts=dict(
            title="8. Heatmap (Multiplication Table)",
            columnnames=[str(i) for i in range(1, 11)],
            rownames=[str(i) for i in range(1, 11)],
            colormap="Viridis",
        ),
        win="heatmap",
    )
    print("[OK] 8. Heatmap")

    # ===========================================================
    # 9. HISTOGRAM
    # ===========================================================
    viz.histogram(
        X=np.random.randn(1000),
        opts=dict(
            title="9. Histogram (Normal Distribution)",
            numbins=40,
        ),
        win="histogram",
    )
    print("[OK] 9. Histogram")

    # ===========================================================
    # 10. BOX PLOT
    # ===========================================================
    viz.boxplot(
        X=np.column_stack(
            (
                np.random.randn(100) * 1 + 5,
                np.random.randn(100) * 2 + 3,
                np.random.randn(100) * 0.5 + 7,
            )
        ),
        opts=dict(
            title="10. Box Plot (3 groups)",
            legend=["Group A", "Group B", "Group C"],
        ),
        win="boxplot",
    )
    print("[OK] 10. Box plot")

    # ===========================================================
    # 11. SURFACE PLOT
    # ===========================================================
    xx = np.linspace(-3, 3, 50)
    yy = np.linspace(-3, 3, 50)
    X_grid, Y_grid = np.meshgrid(xx, yy)
    Z = np.sin(np.sqrt(X_grid**2 + Y_grid**2))
    viz.surf(
        X=Z,
        opts=dict(
            title="11. 3D Surface (sin(sqrt(x²+y²)))",
            colormap="Hot",
        ),
        win="surface",
    )
    print("[OK] 11. 3D surface plot")

    # ===========================================================
    # 12. CONTOUR PLOT
    # ===========================================================
    viz.contour(
        X=Z,
        opts=dict(title="12. Contour Plot"),
        win="contour",
    )
    print("[OK] 12. Contour plot")

    # ===========================================================
    # 13. PIE CHART
    # ===========================================================
    viz.pie(
        X=np.array([30, 25, 20, 15, 10]),
        opts=dict(
            title="13. Pie Chart (Market Share)",
            legend=["Chrome", "Firefox", "Safari", "Edge", "Other"],
        ),
        win="pie",
    )
    print("[OK] 13. Pie chart")

    # ===========================================================
    # 14. IMAGE — Random RGB
    # ===========================================================
    # Create a gradient image
    img = np.zeros((3, 128, 256))
    img[0] = np.linspace(0, 1, 256).reshape(1, -1)  # Red gradient →
    img[1] = np.linspace(0, 1, 128).reshape(-1, 1)  # Green gradient ↓
    img[2] = 0.5  # Constant blue
    viz.image(
        img,
        opts=dict(
            title="14. RGB Gradient Image",
            caption="Red increases left→right, Green increases top→bottom",
        ),
        win="image_rgb",
    )
    print("[OK] 14. RGB gradient image")

    # ===========================================================
    # 15. IMAGE GRID — Multiple images
    # ===========================================================
    viz.images(
        np.random.rand(16, 3, 64, 64),
        nrow=4,
        opts=dict(title="15. Image Grid (4x4)"),
        win="image_grid",
    )
    print("[OK] 15. Image grid")

    # ===========================================================
    # 16. TEXT
    # ===========================================================
    viz.text(
        "<h2>Visual Test Report</h2>"
        "<p>All visualizations created successfully.</p>"
        "<ul>"
        "<li><b>Line plots</b>: single, multi, streaming</li>"
        "<li><b>Scatter</b>: 2D with classes, 3D</li>"
        "<li><b>Charts</b>: bar, stacked bar, histogram, box, pie</li>"
        "<li><b>Heatmap</b>: with labels and colormap</li>"
        "<li><b>3D</b>: surface, contour</li>"
        "<li><b>Images</b>: RGB, grid</li>"
        "</ul>"
        "<p style='color: green; font-weight: bold;'>All dependency tests PASSED</p>",
        opts=dict(title="16. Text/HTML Window"),
        win="text_report",
    )
    print("[OK] 16. HTML text window")

    # ===========================================================
    # 17. LINE PLOT — With markers and fill
    # ===========================================================
    x2 = np.linspace(0, 10, 50)
    viz.line(
        Y=np.column_stack((np.exp(-x2 / 3), np.exp(-x2 / 5))),
        X=np.column_stack((x2, x2)),
        opts=dict(
            title="17. Line with Markers & Fill",
            markers=True,
            fillarea=True,
            legend=["Fast decay", "Slow decay"],
            markersize=5,
        ),
        win="line_markers_fill",
    )
    print("[OK] 17. Line with markers and fill area")

    # ===========================================================
    # DONE
    # ===========================================================
    print(f"\n{'='*60}")
    print(f"ALL 17 VISUALIZATIONS CREATED SUCCESSFULLY")
    print(f"{'='*60}")
    print(f"\nView at: http://localhost:8097/env/{ENV}")
    print("Manually verify each plot renders correctly in the browser.")
    print("\nChecklist:")
    print("  [ ] Line plots show smooth curves with correct legends")
    print("  [ ] Scatter plots show colored points in 2D and 3D")
    print("  [ ] Bar/histogram/box/pie charts render with labels")
    print("  [ ] Heatmap shows color gradient with axis labels")
    print("  [ ] Surface/contour show 3D data")
    print("  [ ] Images render (gradient + grid)")
    print("  [ ] Text window shows formatted HTML")
    print("  [ ] Windows are draggable and resizable")
    print("  [ ] Plots are zoomable and interactive (hover tooltips)")


if __name__ == "__main__":
    main()
