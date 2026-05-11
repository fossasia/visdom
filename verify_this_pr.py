"""
PR #1185 — Box plots with shaded areas (violin plots)
Issue: #769
Branch: Box-plots-with-shaded-areas

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1185.py  (terminal 2)
"""
import visdom
import numpy as np

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1185 — Boxplot fillarea / Violin Plots (Issue #769)")
print("=" * 60)
print()

# Generate overlapping distributions
np.random.seed(42)
data = np.column_stack([
    np.random.randn(300) * 1.0 + 0,    # Group A: centered at 0
    np.random.randn(300) * 1.5 + 2,    # Group B: centered at 2, wider
    np.random.randn(300) * 0.5 + 1,    # Group C: centered at 1, narrow
    np.random.randn(300) * 2.0 + -1,   # Group D: centered at -1, widest
])

# Test 1: Standard box plot
print("Test 1: Standard box plot (baseline)")
viz.boxplot(
    X=data,
    win='boxplot_standard',
    opts=dict(title='Standard Box Plot', legend=['A', 'B', 'C', 'D'])
)
print("  -> Created 'boxplot_standard'")

# Test 2: Violin plot with fillarea=True
print("Test 2: Violin plot (fillarea=True)")
viz.boxplot(
    X=data,
    win='boxplot_violin',
    opts=dict(title='Violin Plot (fillarea=True)',
              legend=['A', 'B', 'C', 'D'],
              fillarea=True)
)
print("  -> Created 'boxplot_violin'")

# Test 3: Box plot with boxpoints control
print("Test 3: Box plot with boxpoints='all'")
small_data = np.column_stack([
    np.random.randn(30),
    np.random.randn(30) + 2,
])
viz.boxplot(
    X=small_data,
    win='boxplot_points',
    opts=dict(title='Box Plot with All Points',
              legend=['X', 'Y'],
              boxpoints='all')
)
print("  -> Created 'boxplot_points'")

print()
print("PASS criteria:")
print("  [x] 'boxplot_standard' shows traditional box-and-whisker plots")
print("  [x] 'boxplot_violin' shows SHADED violin distributions (not boxes)")
print("  [x] Overlapping distributions are clearly distinguishable in violin")
print("  [x] 'boxplot_points' shows individual data points alongside boxes")
print("  FAIL: fillarea=True still renders as standard boxes")
