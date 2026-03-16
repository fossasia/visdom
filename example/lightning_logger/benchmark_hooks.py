"""
Task 4: Profile hook overhead in PyTorch.

Will our implementation with lightning for solving the boilerplate slow the
training process too much?  Let's find out.

Usage:
    python benchmark_hooks.py
"""
import torch
import torch.nn as nn
import time

from model import BigModel


def bench(model, x, iters=500, label=""):
    """Run `iters` forward+backward passes and return elapsed seconds."""
    torch.cuda.synchronize()
    start = time.perf_counter()
    for _ in range(iters):
        out = model(x)
        out.sum().backward()
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    return elapsed


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BigModel().to(device)
    # fake input data, I just need to feed something to the model,
    # I am interested not in the output but to the benchmarks
    x = torch.randn(64, 512).to(device)

    # warmup, I run the model 50 times before measuring anything because the GPUs are lazy
    for _ in range(50):
        out = model(x)
        out.sum().backward()
    torch.cuda.synchronize()

    # ── benchmark WITHOUT hooks ─────────────────────────────────────────
    # run 500 forward and backward passes and time how long it takes
    baseline = bench(model, x)

    # ── benchmark WITH hooks (.item()) ──────────────────────────────────
    handles = []  # store references to every hook
    hook_data = {}  # dictionary where hooks will dump their data

    # loops through every layer in the model, name is the label,
    # module is the actual layer object itself
    for name, module in model.named_modules():
        def fwd_hook(mod, inp, out, n=name):
            # save the norm (.norm()) of the output of the layer
            # as a plain python number (.item())
            hook_data[n] = out.detach().norm().item()

        def bwd_hook(mod, grad_in, grad_out, n=name):
            # save the norm (.norm()) of the gradient (if produced) of the
            # layer as a plain python number (.item())
            if grad_out[0] is not None:
                hook_data[f"{n}_grad"] = grad_out[0].detach().norm().item()

        # attaches both hooks to the layer
        handles.append(module.register_forward_hook(fwd_hook))
        handles.append(module.register_full_backward_hook(bwd_hook))

    hooked = bench(model, x)
    # remove all hooks, leaving hooks means they keep running forever and
    # slowing everything else down:
    for h in handles:
        h.remove()

    # ── benchmark WITH hooks (no .item()) ───────────────────────────────
    # one little difference: no .item() in fwd_hook() and bwd_hook()
    handles = []
    hook_data = {}
    for name, module in model.named_modules():
        def fwd_hook(mod, inp, out, n=name):
            hook_data[n] = out.detach().norm()  # stays on GPU, no sync

        def bwd_hook(mod, grad_in, grad_out, n=name):
            if grad_out[0] is not None:
                hook_data[f"{n}_grad"] = grad_out[0].detach().norm()  # no .item()

        handles.append(module.register_forward_hook(fwd_hook))
        handles.append(module.register_full_backward_hook(bwd_hook))

    hooked_v2 = bench(model, x)
    for h in handles:
        h.remove()

    # ── test 1: empty hooks ─────────────────────────────────────────────
    # let's measure the slowdown of just having empty hooks,
    # fwd_hook() and bwd_hook() have just a pass, means empty
    handles = []
    for name, module in model.named_modules():
        def fwd_hook(mod, inp, out):
            pass

        def bwd_hook(mod, grad_in, grad_out):
            pass

        handles.append(module.register_forward_hook(fwd_hook))
        handles.append(module.register_full_backward_hook(bwd_hook))

    empty_hooks = bench(model, x)
    for h in handles:
        h.remove()

    # ── test 2: store ref only ──────────────────────────────────────────
    # let's measure the slowdown of giving things to the hooks, but we
    # dont have computations here so no .norm()
    handles = []
    hook_data = {}
    for name, module in model.named_modules():
        def fwd_hook(mod, inp, out, n=name):
            hook_data[n] = out.detach()  # just store, no norm

        def bwd_hook(mod, grad_in, grad_out, n=name):
            if grad_out[0] is not None:
                hook_data[f"{n}_grad"] = grad_out[0].detach()

        handles.append(module.register_forward_hook(fwd_hook))
        handles.append(module.register_full_backward_hook(bwd_hook))

    store_hooks = bench(model, x)
    for h in handles:
        h.remove()

    # ── test 3: norm every 100 steps ────────────────────────────────────
    # let's measure now the slowdown of the computations, but in a
    # realistic case, so in the case in which we compute norm only every
    # 100 steps: in fact, when we monitoring, we dont need to log every
    # single step
    handles = []
    hook_data = {}
    step = [0]
    for name, module in model.named_modules():
        def fwd_hook(mod, inp, out, n=name):
            if step[0] % 100 == 0:
                hook_data[n] = out.detach().norm()

        def bwd_hook(mod, grad_in, grad_out, n=name):
            if step[0] % 100 == 0 and grad_out[0] is not None:
                hook_data[f"{n}_grad"] = grad_out[0].detach().norm()

        handles.append(module.register_forward_hook(fwd_hook))
        handles.append(module.register_full_backward_hook(bwd_hook))

    torch.cuda.synchronize()
    start = time.perf_counter()
    for _ in range(500):
        out = model(x)
        out.sum().backward()
        step[0] += 1
    torch.cuda.synchronize()
    sampled_hooks = time.perf_counter() - start
    for h in handles:
        h.remove()

    # ── results ─────────────────────────────────────────────────────────
    def pct(t):
        return ((t - baseline) / baseline) * 100

    print(f"baseline:                       {baseline:.3f}s")
    print(f"hooks (.item()):                {hooked:.3f}s  -> {pct(hooked):.1f}% overhead")
    print(f"hooks (no .item()):             {hooked_v2:.3f}s  -> {pct(hooked_v2):.1f}% overhead")
    print(f"empty hooks:                    {empty_hooks:.3f}s  -> {pct(empty_hooks):.1f}% overhead")
    print(f"store ref only:                 {store_hooks:.3f}s  -> {pct(store_hooks):.1f}% overhead")
    print(f"norm every 100 steps:           {sampled_hooks:.3f}s  -> {pct(sampled_hooks):.1f}% overhead")
    print()
    print("Takeaway: avoid .item() inside hooks (it forces a GPU sync)")
    print("and sample at a reasonable interval instead of every step.")


if __name__ == "__main__":
    main()
