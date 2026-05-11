"""
PR #1216 — Fix append/update support for 3D scatter plots
Issue: #702
Branch: 3D-scatter-issue

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1216.py  (terminal 2)
"""
import visdom
import numpy as np
import time

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1216 — 3D Scatter Append/Update (Issue #702)")
print("=" * 60)
print()

# Test 1: 3D scatter -> 3D append (THE BUG CASE)
print("Test 1: Create 3D scatter, then append 3D points")
try:
    win1 = viz.scatter(
        X=np.random.rand(20, 3),
        win='scatter3d_append',
        opts=dict(title='3D Scatter Append Test', markersize=5)
    )
    time.sleep(0.5)
    viz.scatter(
        X=np.random.rand(20, 3) + 1.0,
        win=win1,
        update='append',
        opts=dict(markersize=5)
    )
    print("  -> PASS: 3D -> 3D append worked")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 2: Multiple sequential 3D appends
print("Test 2: Multiple sequential 3D appends")
try:
    win2 = viz.scatter(
        X=np.random.rand(15, 3),
        win='scatter3d_multi',
        opts=dict(title='3D Multi-Append', markersize=4)
    )
    for i in range(1, 5):
        time.sleep(0.3)
        viz.scatter(
            X=np.random.rand(15, 3) + i,
            win=win2,
            update='append',
            opts=dict(markersize=4)
        )
    print("  -> PASS: 4 sequential appends to 3D scatter worked")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 3: 3D scatter with labels + append
print("Test 3: 3D scatter with labeled clusters + append")
try:
    Y_labels = np.ones(20, dtype=int)
    win3 = viz.scatter(
        X=np.random.rand(20, 3),
        Y=Y_labels,
        win='scatter3d_labels',
        opts=dict(title='3D Labeled + Append', markersize=5,
                  legend=['Cluster 1'])
    )
    time.sleep(0.5)
    Y_labels2 = np.ones(20, dtype=int) * 2
    viz.scatter(
        X=np.random.rand(20, 3) + 2,
        Y=Y_labels2,
        win=win3,
        update='append',
        opts=dict(markersize=5, legend=['Cluster 1', 'Cluster 2'])
    )
    print("  -> PASS: Labeled 3D scatter append worked")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 4: 2D scatter still works (regression)
print("Test 4: 2D scatter append — regression check")
try:
    win4 = viz.scatter(
        X=np.random.rand(20, 2),
        win='scatter2d_regression',
        opts=dict(title='2D Scatter Regression', markersize=6)
    )
    time.sleep(0.3)
    viz.scatter(
        X=np.random.rand(20, 2) + 1,
        win=win4,
        update='append',
    )
    print("  -> PASS: 2D scatter append still works")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()
print("PASS criteria:")
print("  [x] 'scatter3d_append' shows ~40 points in two clusters (3D view)")
print("  [x] 'scatter3d_multi' shows ~75 points across 5 positions")
print("  [x] 'scatter3d_labels' shows two colored clusters in 3D")
print("  [x] 'scatter2d_regression' works as before (2D)")
print("  FAIL: Error on 3D append, or only initial points shown")
