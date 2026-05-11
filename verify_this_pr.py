"""
PR #1176 — Fix Plotly image figure not rendered due to type collision
Issue: #735
Branch: Plotly-image-figure-plotted-issue

Run: python -m visdom.server  (terminal 1)
     python verify_this_pr.py  (terminal 2)

Requires: pip install plotly
"""
import visdom
import numpy as np

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    raise ImportError("Install plotly: pip install plotly")

print("=" * 60)
print("PR #1176 — Plotly Image Figure Type Collision (Issue #735)")
print("=" * 60)
print()

# Test 1: px.imshow — this was broken before the fix
print("Test 1: px.imshow() with random RGB image")
img_data = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
fig1 = px.imshow(img_data, title="px.imshow Random Image")
viz.plotlyplot(fig1, win='plotly_imshow_test')
print("  -> Created 'plotly_imshow_test'")

# Test 2: px.imshow with a grayscale array
print("Test 2: px.imshow() with grayscale heatmap")
heatmap = np.random.rand(50, 50)
fig2 = px.imshow(heatmap, title="px.imshow Grayscale Heatmap")
viz.plotlyplot(fig2, win='plotly_imshow_gray')
print("  -> Created 'plotly_imshow_gray'")

# Test 3: Native visdom image should still work
print("Test 3: Native visdom image (should still work)")
viz.image(np.random.rand(3, 100, 100), win='native_image_test',
          opts=dict(title='Native Visdom Image'))
print("  -> Created 'native_image_test'")

# Test 4: Regular plotly plot (non-image, regression check)
print("Test 4: Regular plotly bar chart (regression check)")
fig3 = go.Figure(data=go.Bar(x=[1, 2, 3], y=[3, 1, 2]))
fig3.update_layout(title="Regular Bar Chart")
viz.plotlyplot(fig3, win='plotly_bar_regression')
print("  -> Created 'plotly_bar_regression'")

print()
print("PASS criteria:")
print("  [x] 'plotly_imshow_test' shows a colorful random image (Plotly rendered)")
print("  [x] 'plotly_imshow_gray' shows a grayscale heatmap (Plotly rendered)")
print("  [x] 'native_image_test' shows a native visdom image (still works)")
print("  [x] 'plotly_bar_regression' shows a normal bar chart")
print("  FAIL: 'plotly_imshow_test' is blank/empty (routed to wrong handler)")
