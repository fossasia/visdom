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
# this is resolved pre-populate sys.modules with dummy stand-in for
# the shim before collection. Python's import machinery checks sys.modules
# first, so pkgutil's __import__() call finds it already "imported" and never
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
        """Undo whatever the test's autolog() call patched, via the real
        VisdomSklearnLogger.unpatch() -- not a hand-picked subset of
        classes. autolog() patches every class sklearn.utils.all_estimators()
        returns (200+), so anything less than the real unpatch() leaves
        most of them permanently monkey-patched for every test file run
        afterwards in the same process (see
        test_unpatch_restores_every_patched_class_not_just_a_few, which
        guards against exactly this)."""
        if VisdomSklearnLogger.active is not None:
            VisdomSklearnLogger.active.unpatch()

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

    def test_gridsearchcv_under_threading_backend_still_logs_exactly_once(self):
        """Regression test for a flagged issue: GridSearchCV/RandomizedSearchCV
        with a threading-based joblib backend (n_jobs > 1 under
        joblib.parallel_backend("threading")) dispatches inner fit() calls
        to worker threads."""
        import joblib
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GridSearchCV
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=100, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            gs = GridSearchCV(LogisticRegression(), {"C": [0.1, 1.0]}, cv=3, n_jobs=4)
            with joblib.parallel_backend("threading"):
                gs.fit(X, y)
        run.finish()

        events = self._events(run)
        fit_events = [e for e in events if e["type"] == "fit"]
        cv_fit_events = [e for e in events if e["type"] == "cv_fit"]
        self.assertEqual(
            len(fit_events),
            0,
            "inner fits dispatched to worker threads must not be logged "
            "as separate top-level fits",
        )
        self.assertEqual(len(cv_fit_events), 1)

    def test_unpatch_restores_every_patched_class_not_just_a_few(self):
        """Regression test for a flagged issue: autolog() patches every
        class sklearn.utils.all_estimators() returns (200+), but an
        earlier version of this test file's own cleanup only restored 4
        hand-picked classes, leaving ~204 others permanently patched with
        VisdomSklearnLogger.active set to None -- meaning any later code
        calling .fit() on one of them (in this process, for the rest of
        its life) would crash with AttributeError: 'NoneType' object has
        no attribute '_depth' (or now, '_enter_fit'). unpatch() must
        restore literally everything it patched, verified against the
        real, complete list all_estimators() returns rather than a
        hand-picked sample."""
        from sklearn.utils import all_estimators
        from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

        all_ests = list(all_estimators())
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis)

        patched_before = sum(
            1 for _, cls in all_ests if getattr(cls.fit, "_visdom_patched", False)
        )
        self.assertGreater(
            patched_before, 100, "sanity check: autolog() should patch 100+ classes"
        )

        VisdomSklearnLogger.active.unpatch()

        still_patched = [
            name for name, cls in all_ests if getattr(cls.fit, "_visdom_patched", False)
        ]
        self.assertEqual(
            still_patched,
            [],
            "these classes were left monkey-patched: {}".format(still_patched),
        )
        self.assertFalse(getattr(GridSearchCV.fit, "_visdom_patched", False))
        self.assertFalse(getattr(RandomizedSearchCV.fit, "_visdom_patched", False))

        # A class nowhere near the old hardcoded 4-class list must work
        # normally post-unpatch -- this is the exact scenario that used
        # to crash with AttributeError before
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=20, n_features=4, random_state=0)
        clf = RandomForestClassifier(n_estimators=3).fit(X, y)
        self.assertTrue(hasattr(clf, "estimators_"))

    def test_unpatch_is_idempotent(self):
        from sklearn.linear_model import LogisticRegression

        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis)
        instance = VisdomSklearnLogger.active
        instance.unpatch()
        instance.unpatch()  # must not raise
        self.assertFalse(getattr(LogisticRegression.fit, "_visdom_patched", False))

    def test_calling_autolog_again_without_unpatching_first_does_not_break_it(self):
        """Regression test for a flagged issue: autolog() called a second
        time (as the class docstring explicitly shows as supported,
        without requiring the caller to unpatch() first) used to leave
        the *new* instance's _patched list empty, because _patch() skips
        every class whose fit is already marked patched -- it had no way
        to know the first instance had already patched everything. The
        new instance's own unpatch() would then restore nothing while
        still clearing `active`, leaving every class wrapped with the
        first instance's now-orphaned patched_fit, which crashed on the
        very next fit() call. autolog() now unpatches any previous
        active instance first, so the second call always starts from a
        genuinely clean slate."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=30, n_features=4, random_state=0)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis)
            first_active = VisdomSklearnLogger.active

            VisdomSklearnLogger.autolog(viz=self.vis)  # again, no unpatch() in between
            second_active = VisdomSklearnLogger.active

        self.assertIsNot(first_active, second_active)
        self.assertGreater(
            len(second_active._patched),
            100,
            "the second instance must have recorded (and thus be able to "
            "restore) everything it patched, same as a first call would",
        )

        second_active.unpatch()
        # this used to crash with AttributeError: 'NoneType' object has
        # no attribute '_enter_fit' -- active was cleared but the
        # classes were still wrapped with the first instance's fit.
        clf = LogisticRegression().fit(X, y)
        self.assertTrue(hasattr(clf, "coef_"))

    def test_enter_fit_decides_top_level_at_entry_not_at_exit(self):
        """Regression test for a flagged issue: two genuinely independent
        top-level fit() calls overlapping in time (neither nested inside
        the other) used to depend on *finishing* order -- whichever fit
        finished first would see the shared depth drop to 1 (not 0) and
        silently never get logged; only whichever finished *last* would
        see depth reach 0 and get logged. That's not fully fixable with
        a shared counter alone (a second, unrelated top-level call is
        indistinguishable from a legitimate nested one purely from the
        counter's perspective -- see _exit_fit's docstring), but it's now
        decided once at *entry* instead of racily at exit, which this
        tests directly against _enter_fit/_exit_fit rather than via a
        real, timing-dependent thread race (which would make this test
        itself flaky).

        With entry-time semantics: whichever call enters while depth is
        genuinely 0 is "top-level" -- decided then and there, and later
        exits (in any order) don't change that earlier decision.
        """
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis)
        logger = VisdomSklearnLogger.active
        self.addCleanup(logger.unpatch)

        # Call A enters first (depth 0->1): top-level.
        a_is_top_level = logger._enter_fit()
        # Call B enters while A is still in flight (depth 1->2): not
        # top-level, whether or not it's actually related to A.
        b_is_top_level = logger._enter_fit()
        self.assertTrue(a_is_top_level)
        self.assertFalse(b_is_top_level)

        # A finishes FIRST (depth 2->1) -- under the old exit-time check
        # (`depth_after == 0`), this would have incorrectly decided "not
        # top-level" for A, since depth is 1, not 0, at this point. Under
        # entry-time semantics, A's already-decided True is unaffected by
        # what order things exit in.
        logger._exit_fit()
        self.assertTrue(a_is_top_level, "A's top-level status must not change on exit")

        # B finishes last (depth 1->0).
        logger._exit_fit()
        self.assertFalse(
            b_is_top_level, "B's top-level status must not change on exit either"
        )

    def test_keyword_argument_fit_call_is_tracked_correctly(self):
        """Regression test for a flagged issue: the wrapper extracted X/y
        only from positional args, so estimator.fit(X=X, y=y) -- valid,
        common usage -- silently passed None into the tracking logic. The
        fit() call itself always worked fine (the *real* sklearn fit
        received the kwargs correctly regardless); only this integration's
        own bookkeeping was blind to keyword-form arguments. The result
        was a tracking event silently recording dataset_shape=None and
        train_score=None even though the fit succeeded normally --
        exactly the kind of wrong-but-not-crashing value that, once
        written to a run's append-only .jsonl record, can't be corrected
        by fixing the code afterwards."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=50, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            LogisticRegression().fit(X=X, y=y)  # both keyword
        run.finish()

        fit_events = [e for e in self._events(run) if e["type"] == "fit"]
        self.assertEqual(len(fit_events), 1)
        data = fit_events[0]["data"]
        self.assertEqual(data["dataset_shape"], [50, 4])
        self.assertIsInstance(data["train_score"], float)

    def test_mixed_positional_and_keyword_fit_call_is_tracked_correctly(self):
        """Same as the above, for the equally valid fit(X, y=y) form
        (X positional, y by keyword) -- not just the fully-keyword case."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.datasets import make_classification

        X, y = make_classification(n_samples=40, n_features=4, random_state=0)
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_fake_send):
            VisdomSklearnLogger.autolog(viz=self.vis, run=run)
            LogisticRegression().fit(X, y=y)  # X positional, y by keyword
        run.finish()

        fit_events = [e for e in self._events(run) if e["type"] == "fit"]
        data = fit_events[0]["data"]
        self.assertEqual(data["dataset_shape"], [40, 4])
        self.assertIsInstance(data["train_score"], float)


if __name__ == "__main__":
    unittest.main()
