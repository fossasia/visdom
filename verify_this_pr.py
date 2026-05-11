"""
PR #1046 — Auto-scroll for TextPane streaming logs
Issue: #787
Branch: Auto-scrolling-for-textarea

Run: python -m visdom.server  (terminal 1)
     python verify_this_pr.py  (terminal 2)
"""
import visdom
import time

viz = visdom.Visdom()
assert viz.check_connection(), "Visdom server not running!"

print("=" * 60)
print("PR #1046 — TextPane Auto-Scroll (Issue #787)")
print("=" * 60)
print()
print("Streaming 100 log lines to 'auto_scroll_test' window...")
print("Watch the UI at http://localhost:8097")
print()

win = viz.text("=== Auto-Scroll Streaming Test ===<br>", win='auto_scroll_test')

for i in range(1, 101):
    viz.text(
        f"[{time.strftime('%H:%M:%S')}] Log line {i:03d}: "
        f"value={i * 0.1:.1f}<br>",
        win=win,
        append=True
    )
    if i == 30:
        print("  -> 30 lines sent. TRY: scroll UP in the text pane now.")
        print("     Auto-scroll should PAUSE while you're scrolled up.")
    if i == 60:
        print("  -> 60 lines sent. TRY: scroll back to BOTTOM.")
        print("     Auto-scroll should RESUME.")
    time.sleep(0.2)

print()
print("Done streaming 100 lines.")
print()
print("PASS criteria:")
print("  [x] Text pane auto-scrolls to bottom as new lines appear")
print("  [x] Scrolling UP pauses auto-scroll (you can read old lines)")
print("  [x] Scrolling back to BOTTOM resumes auto-scroll")
print("  FAIL: Scrollbar stays at top / never moves")
