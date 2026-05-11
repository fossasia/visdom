"""
PR #1044 — Fix backend crash and UI desync on environment deletion
Issue: #887
Branch: Removing-Envs-is-buggy

Run: python -m visdom.server  (terminal 1)
     python verify_this_pr.py  (terminal 2)
"""
import visdom
import time

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1044 — Environment Deletion Fix (Issue #887)")
print("=" * 60)

# Step 1: Create test environments
viz_env1 = visdom.Visdom(env='test_delete_env_1')
viz_env1.text("This environment will be deleted. Delete it from the UI.")

viz_env2 = visdom.Visdom(env='test_delete_env_2')
viz_env2.text("This environment should survive after deleting env_1.")

# Step 2: Create an unsaved/forked env (the crash scenario)
viz_env3 = visdom.Visdom(env='test_delete_unsaved')
viz_env3.text("Unsaved env — delete without saving first.")

print()
print("Created 3 test environments:")
print("  - test_delete_env_1")
print("  - test_delete_env_2")
print("  - test_delete_unsaved")
print()
print("MANUAL STEPS:")
print("  1. Open http://localhost:8097")
print("  2. Select 'test_delete_env_1' in the sidebar")
print("  3. Click the trash/delete icon to delete it")
print("  4. Select 'test_delete_unsaved' and delete it WITHOUT saving")
print()
print("PASS criteria:")
print("  [x] UI removes deleted env immediately (no stale entry)")
print("  [x] No crash in server terminal")
print("  [x] 'test_delete_env_2' is still accessible and shows its text")
print("  [x] Creating a NEW environment after deletion works fine")
print()

# Step 3: After user deletes, try creating a new env
input("Press Enter AFTER you've deleted the envs in the UI...")

viz_new = visdom.Visdom(env='test_post_delete_new')
viz_new.text("Created after deletion — if you see this, no crash!")
print()
print("Created 'test_post_delete_new' — check it appears in the UI.")
print("If server is still running and this env shows up: PASS")
