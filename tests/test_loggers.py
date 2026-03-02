#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for visdom.loggers (base math, Visdom client, Lightning)."""

import math
from unittest.mock import MagicMock

import pytest
import torch
import torch.nn as nn

from visdom.grad_norm import compute_grad_norm, compute_layer_grad_norms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params(*grad_vectors):
    params = []
    for g in grad_vectors:
        p = nn.Parameter(torch.zeros_like(g))
        p.grad = g.clone()
        params.append(p)
    return params


def _trained_model():
    model = nn.Sequential(nn.Linear(4, 2), nn.Linear(2, 1))
    model(torch.randn(3, 4)).sum().backward()
    return model


# ---------------------------------------------------------------------------
# compute_grad_norm
# ---------------------------------------------------------------------------

class TestComputeGradNorm:
    def test_l2_single_param(self):
        assert compute_grad_norm(_params(torch.tensor([3.0, 4.0]))) == pytest.approx(5.0)

    def test_l2_multiple_params(self):
        params = _params(torch.tensor([0.1, 0.2]), torch.tensor([0.3]))
        expected = math.sqrt(0.01 + 0.04 + 0.09)
        assert compute_grad_norm(params, 2.0) == pytest.approx(expected, rel=1e-5)

    def test_l1_norm(self):
        # L1([1,-2]) = 3, L1([3]) = 3 → global L1([3,3]) = 6
        assert compute_grad_norm(
            _params(torch.tensor([1.0, -2.0]), torch.tensor([3.0])), 1.0
        ) == pytest.approx(6.0, rel=1e-5)

    def test_no_grads_returns_zero(self):
        assert compute_grad_norm([nn.Parameter(torch.ones(3))], 2.0) == 0.0

    def test_mixed_none_grads_skipped(self):
        no_grad = nn.Parameter(torch.ones(3))
        with_grad = nn.Parameter(torch.zeros(2))
        with_grad.grad = torch.tensor([3.0, 4.0])
        assert compute_grad_norm([no_grad, with_grad], 2.0) == pytest.approx(5.0)

    def test_inf_norm_type(self):
        # inf-norm = max absolute gradient element across all params
        params = _params(torch.tensor([1.0, -5.0, 3.0]), torch.tensor([2.0]))
        assert compute_grad_norm(params, float('inf')) == pytest.approx(5.0)

    def test_invalid_norm_type_raises(self):
        with pytest.raises(ValueError, match="norm_type"):
            compute_grad_norm(_params(torch.tensor([1.0])), norm_type=0.0)


# ---------------------------------------------------------------------------
# compute_layer_grad_norms
# ---------------------------------------------------------------------------

class TestComputeLayerGradNorms:
    def test_keys_match_named_parameters(self):
        model = _trained_model()
        layer_norms = compute_layer_grad_norms(model, 2.0)
        param_names = {n for n, p in model.named_parameters() if p.grad is not None}
        assert set(layer_norms.keys()) == param_names

    def test_values_match_per_param_norm(self):
        # Each value must equal the L2 norm of that parameter's gradient tensor.
        model = _trained_model()
        layer_norms = compute_layer_grad_norms(model, 2.0)
        for name, param in model.named_parameters():
            if param.grad is not None:
                expected = param.grad.norm(2.0).item()
                assert layer_norms[name] == pytest.approx(expected, rel=1e-5)

    def test_empty_when_no_grads(self):
        assert compute_layer_grad_norms(nn.Linear(2, 1), 2.0) == {}

    def test_consistent_with_global_norm(self):
        model = _trained_model()
        layer_norms = compute_layer_grad_norms(model, 2.0)
        from_layers = math.sqrt(sum(v ** 2 for v in layer_norms.values()))
        direct = compute_grad_norm(model.parameters(), 2.0)
        assert from_layers == pytest.approx(direct, rel=1e-5)

    def test_invalid_norm_type_raises(self):
        with pytest.raises(ValueError, match="norm_type"):
            compute_layer_grad_norms(_trained_model(), norm_type=-1.0)


# ---------------------------------------------------------------------------
# Visdom.log_gradient_norm   (mocked server — no real Visdom needed)
# ---------------------------------------------------------------------------

class TestLogGradientNorm:
    @pytest.fixture
    def vis(self):
        import visdom as _v
        mock = MagicMock()
        mock.env = "main"
        # Bind the real method to the mock so line/bar calls are intercepted.
        mock.log_gradient_norm = _v.Visdom.log_gradient_norm.__get__(mock)
        return mock

    @pytest.fixture
    def model(self):
        m = nn.Linear(4, 2)
        m(torch.randn(3, 4)).sum().backward()
        return m

    def test_returns_positive_float(self, vis, model):
        norm = vis.log_gradient_norm(model, step=0)
        assert isinstance(norm, float) and norm > 0.0

    def test_line_called_once(self, vis, model):
        vis.log_gradient_norm(model, step=0)
        vis.line.assert_called_once()

    def test_always_uses_append(self, vis, model):
        vis.log_gradient_norm(model, step=0)
        vis.log_gradient_norm(model, step=1)
        for _, kw in vis.line.call_args_list:
            assert kw["update"] == "append"

    def test_bar_not_called_by_default(self, vis, model):
        vis.log_gradient_norm(model, step=0)
        vis.bar.assert_not_called()

    def test_bar_called_when_per_layer(self, vis, model):
        vis.log_gradient_norm(model, step=0, per_layer=True)
        vis.bar.assert_called_once()

    def test_bar_win_derived_from_win(self, vis, model):
        vis.log_gradient_norm(model, step=0, win="my_norm", per_layer=True)
        _, kw = vis.bar.call_args
        assert kw["win"] == "my_norm_layers"

    def test_custom_win_forwarded(self, vis, model):
        vis.log_gradient_norm(model, step=0, win="custom")
        _, kw = vis.line.call_args
        assert kw["win"] == "custom"

    def test_custom_env_forwarded(self, vis, model):
        vis.log_gradient_norm(model, step=0, env="exp42")
        _, kw = vis.line.call_args
        assert kw["env"] == "exp42"

    def test_env_falls_back_to_self_env(self, vis, model):
        vis.log_gradient_norm(model, step=0)
        _, kw = vis.line.call_args
        assert kw["env"] == "main"

    def test_opts_merged(self, vis, model):
        vis.log_gradient_norm(model, step=0, opts={"title": "Custom"})
        _, kw = vis.line.call_args
        assert kw["opts"]["title"] == "Custom"

    def test_non_module_raises_type_error(self, vis):
        with pytest.raises(TypeError, match="torch.nn.Module"):
            vis.log_gradient_norm("not_a_model", step=0)

    def test_l1_and_l2_differ(self, vis, model):
        n1 = vis.log_gradient_norm(model, step=0, norm_type=1.0)
        n2 = vis.log_gradient_norm(model, step=0, norm_type=2.0)
        assert n1 != pytest.approx(n2)

    def test_no_grads_returns_zero(self, vis):
        norm = vis.log_gradient_norm(nn.Linear(2, 1), step=0)
        assert norm == 0.0


# ---------------------------------------------------------------------------
# Lightning tests   (skip only Lightning-specific tests when unavailable)
# ---------------------------------------------------------------------------

try:
    import lightning.pytorch  # noqa: F401
    _HAS_LIGHTNING = True
except (ImportError, ModuleNotFoundError):
    try:
        import pytorch_lightning  # noqa: F401
        _HAS_LIGHTNING = True
    except (ImportError, ModuleNotFoundError):
        _HAS_LIGHTNING = False

if _HAS_LIGHTNING:
    from visdom.lightning_logger import GradientNormCallback, VisdomLogger  # noqa: E402
else:  # pragma: no cover
    GradientNormCallback = None  # type: ignore[assignment]
    VisdomLogger = None  # type: ignore[assignment]


def _mock_pl_module():
    """MagicMock with real nn.Linear gradients so named_parameters() works."""
    real = nn.Linear(4, 2)
    real(torch.randn(3, 4)).sum().backward()
    m = MagicMock()
    m.named_parameters = real.named_parameters
    m.parameters = real.parameters
    m.global_step = 0
    return m


def _mock_trainer(step=0):
    t = MagicMock()
    t.global_step = step
    return t


# ---- VisdomLogger properties ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestVisdomLoggerProperties:
    def test_name(self):
        assert VisdomLogger(name="proj", fail_on_no_connection=False).name == "proj"

    def test_version_default_is_string(self):
        v = VisdomLogger(fail_on_no_connection=False).version
        assert isinstance(v, str) and v

    def test_version_explicit(self):
        assert VisdomLogger(version=7, fail_on_no_connection=False).version == 7

    def test_env_derived(self):
        lg = VisdomLogger(name="p", version="r1", fail_on_no_connection=False)
        assert lg._env == "p-vr1"

    def test_env_explicit_override(self):
        assert VisdomLogger(env="custom", fail_on_no_connection=False)._env == "custom"


# ---- VisdomLogger.log_metrics ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestVisdomLoggerLogMetrics:
    @pytest.fixture
    def logger(self):
        lg = VisdomLogger(name="t", version="0", fail_on_no_connection=False)
        lg._viz = MagicMock()
        lg._viz.check_connection.return_value = True
        return lg

    def test_one_line_per_metric(self, logger):
        logger.log_metrics({"loss": 0.5, "acc": 0.9}, step=1)
        assert logger._viz.line.call_count == 2

    def test_epoch_key_skipped(self, logger):
        logger.log_metrics({"loss": 0.5, "epoch": 3}, step=5)
        assert logger._viz.line.call_count == 1

    def test_x_falls_back_to_epoch(self, logger):
        logger.log_metrics({"loss": 0.3, "epoch": 7}, step=None)
        _, kw = logger._viz.line.call_args
        assert kw["X"][0] == 7

    def test_first_call_no_update(self, logger):
        logger.log_metrics({"loss": 0.9}, step=0)
        _, kw = logger._viz.line.call_args
        assert kw["update"] is None

    def test_second_call_appends(self, logger):
        logger.log_metrics({"loss": 0.9}, step=0)
        logger.log_metrics({"loss": 0.8}, step=1)
        _, kw = logger._viz.line.call_args
        assert kw["update"] == "append"

    def test_non_scalar_skipped(self, logger):
        logger.log_metrics({"loss": [1, 2, 3]}, step=0)
        logger._viz.line.assert_not_called()

    def test_window_has_env_prefix(self, logger):
        logger.log_metrics({"loss": 0.5}, step=0)
        _, kw = logger._viz.line.call_args
        assert kw["win"].startswith("t-v0/")


# ---- VisdomLogger.log_hyperparams ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestVisdomLoggerLogHyperparams:
    @pytest.fixture
    def logger(self):
        lg = VisdomLogger(name="t", version="0", fail_on_no_connection=False)
        lg._viz = MagicMock()
        return lg

    def test_text_called_once(self, logger):
        logger.log_hyperparams({"lr": 1e-3})
        logger._viz.text.assert_called_once()

    def test_html_contains_key(self, logger):
        logger.log_hyperparams({"learning_rate": 0.001})
        html = logger._viz.text.call_args[0][0]
        assert "learning_rate" in html

    def test_namespace_input(self, logger):
        from argparse import Namespace
        logger.log_hyperparams(Namespace(lr=0.01, epochs=5))
        html = logger._viz.text.call_args[0][0]
        assert "lr" in html and "epochs" in html


# ---- GradientNormCallback validation ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestGradientNormCallbackInit:
    def test_invalid_log_every(self):
        with pytest.raises(ValueError, match="log_every"):
            GradientNormCallback(log_every=0)

    def test_invalid_norm_type(self):
        with pytest.raises(ValueError, match="norm_type"):
            GradientNormCallback(norm_type=-1.0)

    def test_defaults(self):
        cb = GradientNormCallback()
        assert cb.log_every == 1
        assert cb.norm_type == 2.0
        assert cb.per_layer is False
        assert cb.profile_hooks is False


# ---- GradientNormCallback hooks lifecycle ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestGradientNormCallbackHooks:
    def test_hooks_registered_for_fit(self):
        cb = GradientNormCallback()
        pl_module = _mock_pl_module()
        n_params = sum(1 for _ in pl_module.parameters())
        cb.setup(_mock_trainer(), pl_module, stage="fit")
        assert len(cb._handles) == n_params

    def test_hooks_skipped_for_non_fit(self):
        cb = GradientNormCallback()
        cb.setup(_mock_trainer(), _mock_pl_module(), stage="test")
        assert len(cb._handles) == 0

    def test_hooks_removed_on_fit_end(self):
        cb = GradientNormCallback()
        pl_module = _mock_pl_module()
        cb.setup(_mock_trainer(), pl_module, stage="fit")
        assert len(cb._handles) > 0
        cb.on_fit_end(_mock_trainer(), pl_module)
        assert len(cb._handles) == 0


# ---- GradientNormCallback step logging ----

@pytest.mark.skipif(
    not _HAS_LIGHTNING,
    reason="PyTorch Lightning not installed; skipping Lightning logger tests",
)
class TestGradientNormCallbackStep:
    def test_logs_grad_norm(self):
        cb = GradientNormCallback()
        pl_module = _mock_pl_module()
        cb.on_before_optimizer_step(
            _mock_trainer(step=0), pl_module, optimizer=MagicMock()
        )
        keys = [c[0][0] for c in pl_module.log.call_args_list]
        assert "grad_norm" in keys

    def test_norm_is_positive(self):
        cb = GradientNormCallback()
        pl_module = _mock_pl_module()
        cb.on_before_optimizer_step(
            _mock_trainer(step=0), pl_module, optimizer=MagicMock()
        )
        logged_val = pl_module.log.call_args_list[0][0][1]
        assert logged_val > 0.0

    def test_skips_when_off_log_every(self):
        cb = GradientNormCallback(log_every=5)
        pl_module = _mock_pl_module()
        cb.on_before_optimizer_step(
            _mock_trainer(step=3), pl_module, optimizer=MagicMock()
        )
        pl_module.log.assert_not_called()

    def test_per_layer_logs_exact_count(self):
        # Expects one global grad_norm call plus one call per parameter with a grad.
        cb = GradientNormCallback(per_layer=True)
        pl_module = _mock_pl_module()
        n_params = sum(1 for _, p in pl_module.named_parameters() if p.grad is not None)
        cb.on_before_optimizer_step(
            _mock_trainer(step=0), pl_module, optimizer=MagicMock()
        )
        assert pl_module.log.call_count == 1 + n_params

    def test_per_layer_keys_match_param_names(self):
        """Logged keys are grad_norm/<param_name> for every parameter with a grad."""
        cb = GradientNormCallback(per_layer=True)
        pl_module = _mock_pl_module()
        cb.on_before_optimizer_step(
            _mock_trainer(step=0), pl_module, optimizer=MagicMock()
        )
        logged_keys = {c[0][0] for c in pl_module.log.call_args_list}
        expected = {
            f"grad_norm/{n}"
            for n, p in pl_module.named_parameters()
            if p.grad is not None
        }
        assert expected.issubset(logged_keys)

    def test_profile_hooks_logs_hook_ms_via_real_backward(self):
        # Hooks must fire during an actual backward pass and produce a logged value.
        real = nn.Linear(4, 2)
        cb = GradientNormCallback(profile_hooks=True)
        pl_module = MagicMock()
        pl_module.named_parameters = real.named_parameters
        pl_module.parameters = real.parameters
        cb.setup(_mock_trainer(), pl_module, stage="fit")
        # Trigger backward so registered hooks populate timing data.
        real(torch.randn(3, 4)).sum().backward()
        cb.on_before_optimizer_step(_mock_trainer(step=0), pl_module, optimizer=MagicMock())
        keys = [c[0][0] for c in pl_module.log.call_args_list]
        assert "grad_hook_ms" in keys
        hook_val = next(c[0][1] for c in pl_module.log.call_args_list if c[0][0] == "grad_hook_ms")
        assert hook_val >= 0.0

    def test_log_every_boundary(self):
        # step=0 logs; steps 1..log_every-1 skip; step=log_every logs again.
        cb = GradientNormCallback(log_every=5)
        for step in [0, 5, 10]:
            pm = _mock_pl_module()
            cb.on_before_optimizer_step(_mock_trainer(step=step), pm, optimizer=MagicMock())
            pm.log.assert_called()
        for step in [1, 3, 4, 6, 9]:
            pm = _mock_pl_module()
            cb.on_before_optimizer_step(_mock_trainer(step=step), pm, optimizer=MagicMock())
            pm.log.assert_not_called()
