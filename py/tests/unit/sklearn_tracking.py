#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for visdom.loggers.sklearn.VisdomSklearnLogger's optional
RunTracker integration (the ``run=`` parameter).

Uses real scikit-learn estimators (not mocks) against the established
_unconnected_visdom() + patched _send() pattern (tests/unit/plots.py,
tests/unit/tracking_graphs.py, tests/unit/pytorch_tracking.py) -- no real
server, no network, but a genuine fit() call end to end.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

# sklearn.utils.all_estimators() (called by VisdomSklearnLogger.autolog(),
# unmodified pre-existing behavior) walks every sklearn.* submodule via
# pkgutil, including sklearn.externals.array_api_compat.torch -- a shim
# that does `from torch import *` and then blindly re-exec()s every name
# in dir(torch) as `{name} = torch.{name}`. Under pytest specifically
# (not plain Python), pytest's assertion-rewrite import hook injects a
# non-identifier attribute into a freshly-imported module's namespace,
# and this shim's exec() loop can't handle that, raising a SyntaxError
# from deep inside sklearn on first import -- entirely a pytest+sklearn+
# torch environment interaction, unrelated to anything in this PR.
# Reproduces with any test that calls all_estimators() under pytest,
# whether or not run= tracking is involved.
#
# hence to resolve pre-populate sys.modules with dummy stand-in for shim 
# before collection. Python's import machinery checks sys.modules first, so
# pkgutil's __import__() call finds it already "imported" and never
# executes the broken module body. all_estimators() never actually needs
# anything from this shim -- it's just an accidental side effect of
# walking every submodule -- so a stub with no real content behind it is
# harmless here.
import sys
import types

sys.modules.setdefault(
    "sklearn.externals.array_api_compat.torch",
    types.ModuleType("sklearn.externals.array_api_compat.torch"),
)

import visdom
from visdom.loggers import VisdomSklearnLogger
from visdom.tracking import RunTracker
from visdom.tracking.core import RunTracker as _RunTrackerClass


def _unconnected_visdom():
    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
    ):
        client = visdom.Visdom(use_incoming_socket=False)
    client._handle_post = Mock(
        side_effect=AssertionError("unexpected transport call in unit test")
    )
    return client


def _fake_send(msg, **kw):
    return msg.get("win") or "auto_win"


def _read_events_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestSklearnLoggerRunTracking(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()
        # Each test gets a clean patch target: VisdomSklearnLogger.autolog()
        # mutates class-level `active` and monkey-patches sklearn classes
        # globally, so tests must not leak state into each other.
        self.addCleanup(self._unpatch_all)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _unpatch_all():
        """Undo VisdomSklearnLogger.autolog()'s monkey-patching so the
        next test (and any other test file importing sklearn afterwards)
        sees pristine, unpatched estimator classes."""
        import sklearn.linear_model
        import sklearn.model_selection
        import sklearn.neural_network

        for cls in (
            sklearn.linear_model.LogisticRegression,
            sklearn.linear_model.LinearRegression,
            sklearn.neural_network.MLPRegressor,
            sklearn.model_selection.GridSearchCV,
        ):
            if getattr(cls.fit, "_visdom_patched", False):
                # The original unpatched fit is reachable via __wrapped__
                # (functools.wraps sets this); walk back to it.
                original = cls.fit
                while getattr(original, "_visdom_patched", False):
                    original = original.__wrapped__
                cls.fit = original
        VisdomSklearnLogger.active = None

    def _events(self, run):
        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        return _read_events_jsonl(events_path)

    def test_run_none_by_default_does_not_touch_tracking(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=30, n_features=4, random_state=0)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis)  # no run=
            LogisticRegression().fit(X, y)  # must not raise, nothing to check

    def test_plain_estimator_fit_produces_a_structured_fit_event(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=50, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            LogisticRegression().fit(X, y)
        run.finish()

        events = self._events(run)
        fit_events = [e for e in events if e["type"] == "fit"]
        self.assertEqual(len(fit_events), 1)
        data = fit_events[0]["data"]
        self.assertEqual(data["estimator"], "LogisticRegression")
        self.assertIsInstance(data["fit_time"], float)
        self.assertEqual(data["dataset_shape"], [50, 4])
        self.assertIsInstance(data["train_score"], float)
        self.assertIn("C", data["params"])  # real get_params() dict, typed

        text_updates = [
            e["data"]
            for e in events
            if e["type"] == "plot_update" and e["data"]["method"] == "text"
        ]
        self.assertEqual(len(text_updates), 1)

    def test_regressor_fit_tracks_the_residual_scatter(self):
        from sklearn.linear_model import LinearRegression
        from sklearn.datasets import make_regression

        X, y = make_regression(n_samples=40, n_features=3, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            LinearRegression().fit(X, y)
        run.finish()

        scatter_updates = [
            e["data"]
            for e in self._events(run)
            if e["type"] == "plot_update" and e["data"]["method"] == "scatter"
        ]
        self.assertEqual(len(scatter_updates), 1)
        self.assertEqual(scatter_updates[0]["n_points"], 40)

    def test_history_capable_estimator_tracks_the_loss_curve_line(self):
        from sklearn.neural_network import MLPRegressor
        from sklearn.datasets import make_regression
        import warnings

        X, y = make_regression(n_samples=30, n_features=3, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # sklearn ConvergenceWarning
                MLPRegressor(max_iter=20, random_state=0).fit(X, y)
        run.finish()

        line_updates = [
            e["data"]
            for e in self._events(run)
            if e["type"] == "plot_update" and e["data"]["method"] == "line"
        ]
        self.assertEqual(len(line_updates), 1)
        self.assertEqual(line_updates[0]["attr"], "loss_curve_")
        self.assertIsInstance(line_updates[0]["final_value"], float)

    def test_gridsearchcv_produces_one_cv_fit_event_not_one_per_inner_fit(self):
        """GridSearchCV fits an inner estimator once per (candidate x
        fold) plus a final refit -- existing depth-tracking must gate our
        new tracking calls exactly like it already gates the Visdom
        plotting calls, so this must log exactly one 'cv_fit' event, not
        one per inner LogisticRegression.fit() call underneath it."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GridSearchCV
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=60, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            gs = GridSearchCV(LogisticRegression(), {"C": [0.1, 1.0]}, cv=3)
            gs.fit(X, y)
        run.finish()

        events = self._events(run)
        cv_fit_events = [e for e in events if e["type"] == "cv_fit"]
        fit_events = [e for e in events if e["type"] == "fit"]
        self.assertEqual(len(cv_fit_events), 1)
        self.assertEqual(len(fit_events), 0)  # inner fits must not leak through
        data = cv_fit_events[0]["data"]
        self.assertEqual(data["estimator"], "GridSearchCV")
        self.assertEqual(data["n_candidates"], 2)
        self.assertIn("best_score", data)

        bar_updates = [
            e["data"]
            for e in events
            if e["type"] == "plot_update" and e["data"]["method"] == "bar"
        ]
        self.assertEqual(len(bar_updates), 1)
        self.assertEqual(bar_updates[0]["n_candidates"], 2)

    def test_refit_of_the_same_estimator_reuses_the_window_with_seq_2(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=40, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            clf = LogisticRegression()
            clf.fit(X, y)
            clf.fit(X, y)  # same instance, refit
        run.finish()

        text_updates = [
            e["data"]
            for e in self._events(run)
            if e["type"] == "plot_update" and e["data"]["method"] == "text"
        ]
        self.assertEqual(len(text_updates), 2)
        wins = {u["win"] for u in text_updates}
        self.assertEqual(len(wins), 1, "refit must reuse the same window")
        self.assertEqual([u["window_update_seq"] for u in text_updates], [1, 2])

    def test_tracking_never_breaks_fit_even_on_a_finished_run(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=30, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()  # terminal before autolog() even runs
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            clf = LogisticRegression().fit(X, y)  # must not raise
        self.assertTrue(hasattr(clf, "coef_"))  # the fit itself really ran

    def test_unexpected_internal_bug_warns_but_does_not_break_fit(self):
        import warnings
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=30, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(
            _RunTrackerClass, "log_event", side_effect=TypeError("injected bug")
        ):
            with patch.object(self.vis, "_send", side_effect=_fake_send):
                VisdomSklearnLogger.autolog(viz=self.vis, run=run)
                with self.assertWarns(RuntimeWarning):
                    clf = LogisticRegression().fit(X, y)
        self.assertTrue(hasattr(clf, "coef_"))
        run.finish()


if __name__ == "__main__":
    unittest.main()