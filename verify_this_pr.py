"""
PR #1214 — Handle NaN/Inf values in line plot window creation
Issue: #732
Branch: initial-values-are-NaN/Inf

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1214.py  (terminal 2)
"""
import visdom
import numpy as np
import math

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1214 — NaN/Inf Handling in Line Plots (Issue #732)")
print("=" * 60)
print()

# Test 1: All NaN initial values
print("Test 1: Initialize with all NaN values, then append valid data")
try:
    win1 = viz.line(
        Y=np.array([float('nan'), float('nan'), float('nan')]),
        X=np.array([1, 2, 3]),
        win='nan_all_init',
        opts=dict(title='All NaN init -> valid append')
    )
    viz.line(
        Y=np.array([1.0, 2.0, 3.0, 4.0]),
        X=np.array([4, 5, 6, 7]),
        win=win1,
        update='append'
    )
    print("  -> PASS: Window created and appended successfully")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 2: Mix of NaN and valid initial values
print("Test 2: Initialize with NaN + valid mix")
try:
    win2 = viz.line(
        Y=np.array([float('nan'), 2.0, float('nan'), 4.0]),
        X=np.array([1, 2, 3, 4]),
        win='nan_mix_init',
        opts=dict(title='NaN+valid mix init')
    )
    print("  -> PASS: Mixed NaN/valid window created")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 3: Inf initial values
print("Test 3: Initialize with Inf values, then append valid data")
try:
    win3 = viz.line(
        Y=np.array([float('inf'), float('-inf'), float('inf')]),
        X=np.array([1, 2, 3]),
        win='inf_init',
        opts=dict(title='Inf init -> valid append')
    )
    viz.line(
        Y=np.array([1.0, 2.0, 3.0]),
        X=np.array([4, 5, 6]),
        win=win3,
        update='append'
    )
    print("  -> PASS: Inf init + valid append succeeded")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 4: Mix of Inf, NaN, and valid
print("Test 4: Initialize with Inf + NaN + valid mix")
try:
    win4 = viz.line(
        Y=np.array([float('inf'), float('nan'), 3.0, float('-inf')]),
        X=np.array([1, 2, 3, 4]),
        win='inf_nan_mix',
        opts=dict(title='Inf+NaN+valid mix')
    )
    viz.line(
        Y=np.array([5.0, 6.0, 7.0]),
        X=np.array([5, 6, 7]),
        win=win4,
        update='append'
    )
    print("  -> PASS: Mixed Inf/NaN/valid window created and appended")
except Exception as e:
    print(f"  -> FAIL: {e}")

# Test 5: Normal values (regression check)
print("Test 5: Normal values — regression check")
try:
    viz.line(
        Y=np.array([1.0, 2.0, 3.0]),
        X=np.array([1, 2, 3]),
        win='normal_values',
        opts=dict(title='Normal values (regression)')
    )
    print("  -> PASS: Normal plot still works")
except Exception as e:
    print(f"  -> FAIL: {e}")

print()
print("PASS criteria:")
print("  [x] All NaN/Inf init windows are CREATED (not rejected/errored)")
print("  [x] Appended valid data is visible in the plots")
print("  [x] 'normal_values' works perfectly (no regression)")
print("  FAIL: Window creation fails or server returns error for NaN/Inf input")
