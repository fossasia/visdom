"""
PR #1191 — Fix incorrect X tiling when Y.ndim==2 and Y.shape[1]==1
Issue: #761
Branch: fix-plot-for-y-axis

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1191.py  (terminal 2)
"""
import visdom
import numpy as np

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1191 — Fix X Tiling for Y.shape=(M,1) (Issue #761)")
print("=" * 60)
print()

M = 50
X = np.arange(M, dtype=float)

# Test 1: Y.shape = (M, 1) — THE BUG CASE
print("Test 1: Y.shape=(M,1) with explicit X — the main fix")
Y1 = np.sin(np.linspace(0, 2 * np.pi, M)).reshape(M, 1)
try:
    viz.line(Y=Y1, X=X, win='y_m1_explicit_x',
             opts=dict(title='Y=(M,1) + X=(M,) — should be single sine'))
    print("  -> PASS: No error")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 2: Y.shape = (M, 1) with X=None
print("Test 2: Y.shape=(M,1) with X=None")
Y2 = np.random.rand(M, 1)
try:
    viz.line(Y=Y2, win='y_m1_no_x',
             opts=dict(title='Y=(M,1) + X=None — single line'))
    print("  -> PASS: No error")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 3: Y.shape = (1, M) — should still work (regression)
print("Test 3: Y.shape=(1,M) with explicit X — regression check")
Y3 = np.random.rand(1, M)
try:
    viz.line(Y=Y3, X=X, win='y_1m_explicit_x',
             opts=dict(title='Y=(1,M) + X=(M,) — regression check'))
    print("  -> PASS: No error")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 4: Y.shape = (M, 3) — multi-line (should still work)
print("Test 4: Y.shape=(M,3) multi-line — regression check")
Y4 = np.column_stack([np.sin(X / 10), np.cos(X / 10), np.tan(X / 50)])
try:
    viz.line(Y=Y4, X=X, win='y_m3_multiline',
             opts=dict(title='Y=(M,3) multi-line', legend=['sin', 'cos', 'tan']))
    print("  -> PASS: No error")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()
print("PASS criteria:")
print("  [x] 'y_m1_explicit_x' shows a SINGLE smooth sine wave (not garbled)")
print("  [x] 'y_m1_no_x' shows a single line")
print("  [x] 'y_1m_explicit_x' works as before (no regression)")
print("  [x] 'y_m3_multiline' shows 3 separate lines")
print("  FAIL: Shape mismatch error, garbled plot, or multiple lines in test 1")
