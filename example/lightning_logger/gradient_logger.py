"""
Task 5: Gradient norm logger for Visdom.

Attaches backward hooks to every trainable parameter and streams per-layer
and total gradient L2-norms to Visdom in real time.
"""
import torch
from visdom import Visdom


# define the gradient norm logger
class GradientNormLogger:
    def __init__(self, model, viz=None, port=8097, log_every=50):
        self.viz = viz or Visdom(port=port)  # viz connection
        self.model = model
        self.step = 0  # tracking the trainining steps
        self.log_every = log_every  # log every tot step not every single one
        self._handles = []  # stores hook references
        self._attach(model)  # install hooks

    def _attach(self, model):
        # loop through every individual weight/bias in the model
        for name, param in model.named_parameters():
            # skip frozen/non-trainable params:
            if param.requires_grad:
                def hook(grad, layer_name=name):
                    if self.step % self.log_every == 0:  # only do work every tot steps
                        norm = grad.detach().norm(2).item()  # L2 norm will summarize how much large is this gradient
                        # plot it on visdom:
                        self.viz.line(
                            Y=[norm], X=[self.step],
                            win=f"grad_norm/{layer_name}",
                            update='append',
                            opts=dict(title=f"grad norm: {layer_name}",
                                      xlabel="step", ylabel="L2 norm"),
                        )
                # actually install the hook on this parameter
                self._handles.append(param.register_hook(hook))

    def on_step(self):
        if self.step % self.log_every == 0:
            total_norm = torch.nn.utils.clip_grad_norm_(
                self.model.parameters(), float('inf'))
            self.viz.line(
                Y=[total_norm.item()], X=[self.step],
                win="grad_norm/total", update='append',
                opts=dict(title="total gradient norm",
                          xlabel="step", ylabel="L2 norm"),
            )
        self.step += 1

    def detach(self):
        # remove all hooks, leaving hooks means they keep running forever
        # and slowing everything else down:
        for h in self._handles:
            h.remove()
        self._handles.clear()
