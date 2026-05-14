"""
Demo: image_history slider sync — what this PR enables.

Simulates a 10-epoch training loop. At each epoch we log:
  - 'input'      : noisy image fed to the model
  - 'prediction' : model output (noise reduces each epoch)
  - 'ground_truth': clean target

After logging all epochs, Python programmatically steps through
every epoch in sync across all three panes — this was impossible
before this PR. The slider had no Python API.
"""

import time
import numpy as np
import visdom

viz = visdom.Visdom()
assert viz.check_connection(), "Start the server first: python -m visdom.server"

EPOCHS = 10
H, W = 128, 128
WIN_INPUT = "input"
WIN_PRED = "prediction"
WIN_GT = "ground_truth"


def make_ground_truth(epoch):
    """Clean checkerboard whose color shifts per epoch."""
    img = np.zeros((3, H, W), dtype=np.uint8)
    block = 16
    for r in range(H):
        for c in range(W):
            if (r // block + c // block) % 2 == 0:
                img[0, r, c] = 200
                img[1, r, c] = 50 + epoch * 18
            else:
                img[2, r, c] = 200
    return img


def make_noisy(clean, noise_level):
    """Add gaussian noise; noise_level 0=clean, 1=fully noisy."""
    noise = np.random.randn(*clean.shape) * 255 * noise_level
    noisy = np.clip(clean.astype(float) + noise, 0, 255).astype(np.uint8)
    return noisy


# ── simulate training, push one frame per epoch ──────────────────
print("Phase 1 — logging 10 epochs...")
for epoch in range(EPOCHS):
    gt = make_ground_truth(epoch)
    noise = 1.0 - (epoch / (EPOCHS - 1))  # noise drops from 1.0 → 0.0
    pred = make_noisy(gt, noise * 0.6)
    inp = make_noisy(gt, 1.0)  # input is always fully noisy

    opts_base = dict(store_history=True, width=256, height=256)

    viz.image(inp, win=WIN_INPUT, opts=dict(title="Input  (noisy)", **opts_base))
    viz.image(
        pred, win=WIN_PRED, opts=dict(title="Prediction (improving)", **opts_base)
    )
    viz.image(gt, win=WIN_GT, opts=dict(title="Ground Truth", **opts_base))

    print(f"  epoch {epoch:02d}  noise={noise:.2f}")
    time.sleep(0.3)

print("\nAll epochs logged. Open http://localhost:8097 to see three panes.")
time.sleep(2)

# ── Python steps through epochs in sync across all 3 panes ───────
print("Phase 2 — Python syncing all sliders in lockstep (new API)...")
for epoch in range(EPOCHS):
    viz.update_image_slider(WIN_INPUT, epoch)
    viz.update_image_slider(WIN_PRED, epoch)
    viz.update_image_slider(WIN_GT, epoch)
    print(f"  → epoch {epoch:02d}")
    time.sleep(0.6)

# Rewind back to epoch 0
time.sleep(0.5)
print("\nRewinding to epoch 0...")
for epoch in range(EPOCHS - 1, -1, -1):
    viz.update_image_slider(WIN_INPUT, epoch)
    viz.update_image_slider(WIN_PRED, epoch)
    viz.update_image_slider(WIN_GT, epoch)
    time.sleep(0.25)

print("\nDone. All three panes are synced to epoch 0.")
