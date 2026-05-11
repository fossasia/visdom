"""
PR #1238 — Fix multi-environment window rendering
Issue: #1237
Branch: fix-multi-env-preview

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1238.py  (terminal 2)
"""
import visdom
import numpy as np

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1238 — Multi-Environment Window Rendering (Issue #1237)")
print("=" * 60)
print()

# Create Environment A with unique windows
print("Setting up Environment A...")
viz_a = visdom.Visdom(env='multi_test_A')
viz_a.text("Text window from Env A", win='text_a')
viz_a.line(Y=np.sin(np.linspace(0, 4 * np.pi, 100)),
           win='sine_a', opts=dict(title='Sine Wave (Env A)'))
viz_a.bar(X=np.random.rand(5), win='bar_a',
          opts=dict(title='Bar Chart (Env A)'))

# Create Environment B with unique windows
print("Setting up Environment B...")
viz_b = visdom.Visdom(env='multi_test_B')
viz_b.text("Text window from Env B", win='text_b')
viz_b.line(Y=np.cos(np.linspace(0, 4 * np.pi, 100)),
           win='cosine_b', opts=dict(title='Cosine Wave (Env B)'))
viz_b.scatter(X=np.random.rand(30, 2), win='scatter_b',
              opts=dict(title='Scatter (Env B)', markersize=8))

# Create Environment C with overlapping window names
print("Setting up Environment C (has overlapping win name with A)...")
viz_c = visdom.Visdom(env='multi_test_C')
viz_c.text("Text window from Env C (same win name as A)", win='text_a')
viz_c.line(Y=np.random.rand(50), win='random_c',
           opts=dict(title='Random Line (Env C)'))

print()
print("MANUAL STEPS:")
print("  1. Open http://localhost:8097")
print("  2. Hold Ctrl/Cmd and select BOTH 'multi_test_A' and 'multi_test_B'")
print()
print("PASS criteria (A + B selected):")
print("  [x] See ALL 6 windows: text_a, sine_a, bar_a, text_b, cosine_b, scatter_b")
print("  [x] Windows are labeled with their source environment")
print()
print("  3. Now select ALL THREE: multi_test_A, multi_test_B, multi_test_C")
print()
print("PASS criteria (A + B + C selected):")
print("  [x] See windows from all 3 environments")
print("  [x] Overlapping window name 'text_a' shows both A and C versions")
print("  FAIL: Empty view, or only one environment's windows shown")
