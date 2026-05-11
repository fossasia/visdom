"""
PR #1156 — Respect Plotly figure width and height in plotlyplot window
Issue: #788
Branch: plotlyplot-window-size

Run: python -m visdom.server  (terminal 1)
     python verify_this_pr.py  (terminal 2)

Requires: pip install plotly
"""
import visdom

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

try:
    import plotly.graph_objects as go
except ImportError:
    raise ImportError("Install plotly: pip install plotly")

print("=" * 60)
print("PR #1156 — Plotly Figure Size Respect (Issue #788)")
print("=" * 60)
print()

# Small figure: 400x300
fig_small = go.Figure(data=go.Bar(x=[1, 2, 3], y=[1, 3, 2]))
fig_small.update_layout(width=400, height=300, title="Small Plot (400x300)")
viz.plotlyplot(fig_small, win='plotly_size_small')
print("Created 'plotly_size_small' — should be 400x300")

# Medium figure: 640x480
fig_medium = go.Figure(data=go.Scatter(x=[1, 2, 3, 4], y=[2, 4, 3, 5], mode='lines+markers'))
fig_medium.update_layout(width=640, height=480, title="Medium Plot (640x480)")
viz.plotlyplot(fig_medium, win='plotly_size_medium')
print("Created 'plotly_size_medium' — should be 640x480")

# Large figure: 900x600
fig_large = go.Figure(data=go.Bar(x=['A', 'B', 'C', 'D'], y=[4, 2, 5, 3]))
fig_large.update_layout(width=900, height=600, title="Large Plot (900x600)")
viz.plotlyplot(fig_large, win='plotly_size_large')
print("Created 'plotly_size_large' — should be 900x600")

# No explicit size (should use default)
fig_default = go.Figure(data=go.Bar(x=[1, 2], y=[1, 2]))
fig_default.update_layout(title="Default Size (no width/height set)")
viz.plotlyplot(fig_default, win='plotly_size_default')
print("Created 'plotly_size_default' — uses default size")

print()
print("PASS criteria:")
print("  [x] 'plotly_size_small' is visibly SMALLER than the others")
print("  [x] 'plotly_size_large' is visibly LARGER than the others")
print("  [x] Each window roughly matches its specified dimensions")
print("  FAIL: All windows are the same size regardless of layout settings")
