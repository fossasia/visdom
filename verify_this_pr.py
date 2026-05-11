"""
PR #1229 — Fix env matching prefix of another gets overwritten
Issue: #521
Branch: Environment-matching-prefix-of-another-gets-overwritten

Run: python -m visdom.server  (terminal 1)
     python verify_prs/verify_pr_1229.py  (terminal 2)
"""
import visdom

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1229 — Environment Prefix Overwrite Fix (Issue #521)")
print("=" * 60)
print()

# Create environments with shared prefixes
envs = {
    'train': 'I am the "train" environment',
    'training': 'I am the "training" environment',
    'training_v2': 'I am the "training_v2" environment',
    'train_loss': 'I am the "train_loss" environment',
    'test': 'I am the "test" environment',
    'test_results': 'I am the "test_results" environment',
}

for env_name, text in envs.items():
    v = visdom.Visdom(env=env_name)
    v.text(text, win='identity')
    # Also add a unique plot to each
    import numpy as np
    v.line(Y=np.random.rand(20), win='data',
           opts=dict(title=f'Data for {env_name}'))
    print(f"  -> Created env '{env_name}'")

print()
print("MANUAL VERIFICATION:")
print("  1. Open http://localhost:8097")
print("  2. Check the environment dropdown/sidebar")
print()
print("PASS criteria:")
print("  [x] ALL 6 environments appear in the sidebar:")
for env_name in envs:
    print(f"      - {env_name}")
print("  [x] Selecting 'train' shows 'I am the train environment'")
print("  [x] Selecting 'training' shows 'I am the training environment'")
print("  [x] Each env has its OWN independent data/plots")
print("  FAIL: Some envs are missing, or switching envs shows wrong content")
