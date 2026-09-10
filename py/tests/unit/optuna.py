#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the optional Optuna callback integration."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from visdom.integrations import OptunaCallback


pytestmark = pytest.mark.unit


class TestOptunaCallbackCompatibility(unittest.TestCase):
    """The callback handles supported Optuna and Visdom limits."""

    def test_metric_names_fall_back_when_study_has_no_metric_names(self):
        callback = OptunaCallback(Mock())
        study = SimpleNamespace()

        self.assertEqual(callback._metric_names(study, 1), ("objective",))
        self.assertEqual(
            callback._metric_names(study, 2),
            ("objective_0", "objective_1"),
        )

    def test_tags_allow_space_for_reserved_optuna_tags(self):
        callback = OptunaCallback(
            Mock(), tags={"tag-{}".format(index): "" for index in range(14)}
        )
        study = SimpleNamespace(
            study_name="study",
            directions=[SimpleNamespace(name="MINIMIZE")],
        )
        trial = SimpleNamespace(number=1, state=SimpleNamespace(name="COMPLETE"))

        self.assertEqual(len(callback._trial_tags(study, trial)), 20)

    def test_tags_reject_more_than_available_non_reserved_tags(self):
        with self.assertRaisesRegex(ValueError, "at most 14 non-reserved tags"):
            OptunaCallback(
                Mock(), tags={"tag-{}".format(index): "" for index in range(15)}
            )


class TestOptunaCallbackErrorHandling(unittest.TestCase):
    """Payload-building failures follow the configured error policy."""

    def test_dashboard_payload_error_warns_by_default(self):
        callback = OptunaCallback(Mock())

        with (
            patch.object(
                callback,
                "_build_dashboard_payload",
                side_effect=RuntimeError("dashboard payload failed"),
            ),
            self.assertWarnsRegex(RuntimeWarning, "dashboard payload failed"),
        ):
            result = callback.update_dashboard(Mock())

        self.assertFalse(result)

    def test_dashboard_payload_error_is_raised_when_requested(self):
        callback = OptunaCallback(Mock(), raise_on_error=True)

        with (
            patch.object(
                callback,
                "_build_dashboard_payload",
                side_effect=RuntimeError("dashboard payload failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "dashboard payload failed"),
        ):
            callback.update_dashboard(Mock())

    def test_trial_payload_error_warns_by_default(self):
        callback = OptunaCallback(Mock())
        trial = SimpleNamespace(number=7)

        with (
            patch.object(
                callback,
                "_build_payload",
                side_effect=RuntimeError("trial payload failed"),
            ),
            self.assertWarnsRegex(RuntimeWarning, "trial payload failed"),
        ):
            callback(Mock(), trial)

    def test_trial_payload_error_is_raised_when_requested(self):
        callback = OptunaCallback(Mock(), raise_on_error=True)
        trial = SimpleNamespace(number=7)

        with (
            patch.object(
                callback,
                "_build_payload",
                side_effect=RuntimeError("trial payload failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "trial payload failed"),
        ):
            callback(Mock(), trial)


if __name__ == "__main__":
    unittest.main()
