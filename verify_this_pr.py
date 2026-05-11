"""
PR #1021 — Save Plotly figure as image programmatically
Issue: #933
Branch: save-image-without-clicking-in-my-browers

Run: python -m visdom.server  (terminal 1)
     python verify_this_pr.py  (terminal 2)

Requires: pip install plotly kaleido
"""
import visdom
import os

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

try:
    import plotly.graph_objects as go
except ImportError:
    raise ImportError("Install plotly: pip install plotly kaleido")

print("=" * 60)
print("PR #1021 — Save Plotly Figure as Image (Issue #933)")
print("=" * 60)
print()

fig = go.Figure(data=go.Bar(x=['Apples', 'Bananas', 'Cherries'], y=[3, 1, 2]))
fig.update_layout(title="Fruit Sales")

# Test 1: plotlyplot with save_path parameter
print("Test 1: viz.plotlyplot() with save_path='/tmp/pr1021_test1.png'")
try:
    viz.plotlyplot(fig, win='save_plotly_test', save_path='/tmp/pr1021_test1.png')
    if os.path.exists('/tmp/pr1021_test1.png'):
        size = os.path.getsize('/tmp/pr1021_test1.png')
        print(f"  -> PASS: File saved ({size} bytes)")
        print(f"  -> View: xdg-open /tmp/pr1021_test1.png")
    else:
        print("  -> FAIL: File was not created")
except TypeError as e:
    print(f"  -> FAIL: save_path not recognized — {e}")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()

# Test 2: save_plotly_figure standalone method
print("Test 2: viz.save_plotly_figure(fig, '/tmp/pr1021_test2.png')")
try:
    viz.save_plotly_figure(fig, '/tmp/pr1021_test2.png')
    if os.path.exists('/tmp/pr1021_test2.png'):
        size = os.path.getsize('/tmp/pr1021_test2.png')
        print(f"  -> PASS: File saved ({size} bytes)")
        print(f"  -> View: xdg-open /tmp/pr1021_test2.png")
    else:
        print("  -> FAIL: File was not created")
except AttributeError:
    print("  -> FAIL: save_plotly_figure() method does not exist")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()

# Test 3: SVG format
print("Test 3: viz.plotlyplot() with save_path='/tmp/pr1021_test3.svg'")
try:
    viz.plotlyplot(fig, win='save_plotly_svg', save_path='/tmp/pr1021_test3.svg')
    if os.path.exists('/tmp/pr1021_test3.svg'):
        size = os.path.getsize('/tmp/pr1021_test3.svg')
        print(f"  -> PASS: SVG saved ({size} bytes)")
    else:
        print("  -> FAIL: SVG file was not created")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()
print("PASS criteria:")
print("  [x] PNG files created at /tmp/pr1021_test1.png and /tmp/pr1021_test2.png")
print("  [x] SVG file created at /tmp/pr1021_test3.svg")
print("  [x] Plot also visible in Visdom UI")
print("  [x] Backward compatible: plotlyplot without save_path still works")
