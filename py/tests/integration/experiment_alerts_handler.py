#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Integration tests for the alert endpoint and the notification it sends.

Two halves. The endpoint is an ordinary metadata write -- it answers with the
environment's rules, persists them inside the experiment, and is refused on a
readonly server the way the other writes are. The notification is the half
nothing else in the suite can see: a rule is evaluated where the metrics it
watches arrive, so what proves the feature works is that logging a metric to
``/experiments/log`` makes a toast appear on the sockets watching that
environment, with the state behind it written to disk.
"""

import json
from unittest import mock

import pytest

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore

from testutils.fakes import FakeSocket, SpyStore
from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class AlertsTestCase(VisdomHTTPTestCase):
    def set_alert(self, metric="loss", condition="> 2.0", eid="main", **extra):
        alert = {"metric": metric, "condition": condition}
        alert.update(extra)
        return self.post_json(
            "/experiments/alerts", {"action": "set", "eid": eid, "alert": alert}
        )

    def clear_alert(self, metric="loss", condition=None, eid="main"):
        return self.post_json(
            "/experiments/alerts",
            {
                "action": "clear",
                "eid": eid,
                "metric": metric,
                "condition": condition,
            },
        )

    def log_metric(self, value, metric="loss", step=None, eid="main"):
        return self.post_json(
            "/experiments/log",
            {"action": "metrics", "eid": eid, "metrics": {metric: value}, "step": step},
        )

    def stored_alerts(self, eid="main"):
        """The rules as they were written to disk, not as the reply had them."""
        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment(eid)
        return [] if experiment is None else [a.to_dict() for a in experiment.alerts]

    def notifications(self, sub):
        return [
            message["data"]["message"]
            for message in sub.sent
            if message.get("command") == "notification"
        ]

    def subscribe(self, eid="main", sid="sub"):
        sub = FakeSocket(sid, eid)
        self._app.subs[sid] = sub
        return sub


class TestAlertsEndpoint(AlertsTestCase):
    def test_a_rule_is_stored_and_returned(self):
        response = self.set_alert(for_steps=3, message="too high")

        self.assertEqual(response.code, 200)
        rules = json.loads(response.body)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["key"], "loss")
        self.assertEqual(rules[0]["condition"], ">")
        self.assertEqual(rules[0]["threshold"], 2.0)
        self.assertEqual(rules[0]["for_steps"], 3)
        self.assertEqual(rules[0]["message"], "too high")
        self.assertEqual(rules[0]["fire_count"], 0)
        self.assertEqual(self.stored_alerts(), rules)

    def test_a_rule_needs_no_experiment_to_exist_first(self):
        # The order that makes the feature useful: the rule goes on before the
        # run has logged anything for it to judge.
        self.assertEqual(self.stored_alerts(), [])
        self.set_alert()
        self.assertEqual(len(self.stored_alerts()), 1)

    def test_get_answers_with_the_rules(self):
        self.set_alert()
        self.set_alert(condition="stalled", patience=4)

        from_get = self.fetch("/experiments/alerts?eid=main")
        from_post = self.post_json("/experiments/alerts", {"action": "get"})

        self.assertEqual(from_get.code, 200)
        self.assertEqual(json.loads(from_get.body), json.loads(from_post.body))
        self.assertEqual(
            [rule["condition"] for rule in json.loads(from_get.body)],
            [">", "stalled"],
        )

    def test_get_on_an_environment_with_no_rules_is_an_empty_list(self):
        response = self.fetch("/experiments/alerts?eid=never-seen")
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), [])

    def test_restating_a_rule_replaces_it(self):
        self.set_alert(condition="> 2.0")
        rules = json.loads(self.set_alert(condition="> 9.0").body)

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["threshold"], 9.0)

    def test_one_metric_may_carry_two_conditions(self):
        self.set_alert(condition="> 2.0")
        rules = json.loads(self.set_alert(condition="nan").body)

        self.assertEqual([rule["condition"] for rule in rules], [">", "nan"])

    def test_clearing_a_metric_drops_all_of_its_rules(self):
        self.set_alert(condition="> 2.0")
        self.set_alert(condition="nan")
        self.set_alert(metric="acc", condition="< 0.1")

        rules = json.loads(self.clear_alert("loss").body)

        self.assertEqual([rule["key"] for rule in rules], ["acc"])
        self.assertEqual(len(self.stored_alerts()), 1)

    def test_clearing_one_condition_leaves_the_other(self):
        self.set_alert(condition="> 2.0")
        self.set_alert(condition="nan")

        rules = json.loads(self.clear_alert("loss", condition="> 2.0").body)

        self.assertEqual([rule["condition"] for rule in rules], ["nan"])

    def test_set_and_clear_agree_on_a_metric_with_whitespace_around_it(self):
        # Whichever way a rule treats a padded metric name, both halves of
        # this endpoint have to treat it the same way: a rule that can be set
        # is a rule that can be cleared under the name it was set with. The
        # handler holds no opinion of its own about what names a series, and
        # this is what says so if it ever starts to.
        self.set_alert(metric="  loss  ", condition="> 2.0")
        self.assertEqual(len(self.stored_alerts()), 1)

        rules = json.loads(self.clear_alert("  loss  ").body)

        self.assertEqual(rules, [])
        self.assertEqual(self.stored_alerts(), [])

    def test_a_condition_may_be_named_without_its_operand(self):
        self.set_alert(condition="> 2.0")
        rules = json.loads(self.clear_alert("loss", condition=">").body)
        self.assertEqual(rules, [])

    def test_clearing_a_rule_that_was_never_set_is_not_an_error(self):
        self.set_alert()
        response = self.clear_alert("accuracy")
        self.assertEqual(response.code, 200)
        self.assertEqual(len(json.loads(response.body)), 1)

    def test_clearing_on_an_environment_with_no_experiment_is_404(self):
        response = self.clear_alert("loss", eid="never-seen")
        self.assertEqual(response.code, 404)

    def test_a_finished_run_refuses_a_new_rule(self):
        self.log_metric(1.0)
        self.post_json(
            "/experiments/log",
            {"action": "finish", "eid": "main", "status": "finished"},
        )

        response = self.set_alert()

        self.assertEqual(response.code, 409)
        self.assertEqual(self.stored_alerts(), [])

    def test_a_rule_that_does_not_make_sense_is_400(self):
        # One request each, in a loop rather than a parametrize: these are
        # ``AsyncHTTPTestCase`` methods, and pytest cannot parametrize a
        # unittest one -- it silently never passes the argument.
        refused = [
            {"metric": "loss", "condition": ">= 2.0"},
            {"metric": "loss", "condition": "> abc"},
            {"metric": "loss", "condition": ""},
            {"metric": "", "condition": "> 2.0"},
            {"metric": "loss"},
            {"condition": "> 2.0"},
            {"metric": "loss", "condition": "nan", "patience": 3},
            {"metric": "loss", "condition": "> 2.0", "for_steps": 0},
            {"metric": "loss", "condition": "stalled", "goal": "lower"},
            {"metric": "loss", "condition": "nan", "action": "webhook"},
        ]
        for alert in refused:
            with self.subTest(alert=alert):
                response = self.post_json(
                    "/experiments/alerts",
                    {"action": "set", "eid": "main", "alert": alert},
                )
                self.assertEqual(response.code, 400)
        self.assertEqual(self.stored_alerts(), [])

    def test_a_set_without_a_rule_object_is_400(self):
        for body in (
            {"action": "set", "eid": "main"},
            {"action": "set", "eid": "main", "alert": "loss > 2"},
            {"action": "set", "eid": "main", "alert": ["loss", "> 2"]},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post_json("/experiments/alerts", body).code, 400)

    def test_a_refusal_explains_itself_in_the_body(self):
        response = self.set_alert(condition=">= 2.0")

        self.assertEqual(response.code, 400)
        answer = json.loads(response.body)
        self.assertFalse(answer["success"])
        self.assertIn(">=", answer["error"])

    def test_a_condition_outside_latin_1_is_refused_rather_than_breaking(self):
        # The explanation names what the caller sent, and tornado puts a
        # reason= on the HTTP status line, which is latin-1 and cannot carry
        # it. A 400 whose body holds the text can.
        response = self.set_alert(condition="> 2.0\u00b0C")

        self.assertEqual(response.code, 400)
        self.assertFalse(json.loads(response.body)["success"])

    def test_an_environment_name_outside_latin_1_is_refused_the_same_way(self):
        self.log_metric(1.0, eid="env_\u00e9\u00e0\u00fc\u4e2d")
        self.post_json(
            "/experiments/log",
            {
                "action": "finish",
                "eid": "env_\u00e9\u00e0\u00fc\u4e2d",
                "status": "finished",
            },
        )

        response = self.set_alert(eid="env_\u00e9\u00e0\u00fc\u4e2d")

        self.assertEqual(response.code, 409)
        self.assertFalse(json.loads(response.body)["success"])

    def test_a_clear_without_a_metric_is_400(self):
        response = self.post_json(
            "/experiments/alerts", {"action": "clear", "eid": "main"}
        )
        self.assertEqual(response.code, 400)

    def test_an_unknown_action_is_400(self):
        response = self.post_json("/experiments/alerts", {"action": "fire"})
        self.assertEqual(response.code, 400)

    def test_the_rules_survive_a_fork_pointing_at_the_new_environment(self):
        self.set_alert()
        self.post_json("/fork_env", {"prev_eid": "main", "eid": "forked"})

        self.assertEqual(len(self.stored_alerts("forked")), 1)


class TestAlertWritesAreOnlyForChanges(AlertsTestCase):
    """What a change to the rules costs when it is not a change at all.

    A rule lives inside the environment file, so persisting one means writing
    the whole of it -- every window, every metric series, every pane of layout
    beside the few hundred bytes of metadata that actually changed. A request
    that removed no rule has no business queueing that, and marking the
    environment dirty would have the autosave write it a second time.
    """

    def get_app(self):
        # ``ServerState`` keeps its own reference to the store, so the spy has
        # to be what the application builds for itself.
        with mock.patch("visdom.server.app.JSONStore", SpyStore):
            app = super().get_app()
        self.spy = app.storage
        return app

    def dirty(self, eid="main"):
        return self._app.server_state.dirty_envs.get(eid, 0)

    def quiet(self):
        """Forget what setting the rule up cost, and watch only what follows."""
        self.spy.calls["save_env"].clear()
        self._app.server_state.dirty_envs.clear()

    def test_a_clear_that_removes_nothing_writes_nothing(self):
        self.set_alert()
        self.quiet()

        response = self.clear_alert("accuracy")

        self.assertEqual(response.code, 200)
        self.assertEqual(len(json.loads(response.body)), 1)
        self.assertEqual(self.spy.calls["save_env"], [])
        self.assertEqual(self.dirty(), 0)

    def test_a_clear_naming_a_condition_no_rule_has_writes_nothing(self):
        # The other way a clear matches nothing: the metric is watched, but
        # not by a rule with that condition.
        self.set_alert(condition="> 2.0")
        self.quiet()

        response = self.clear_alert("loss", condition="stalled")

        self.assertEqual(response.code, 200)
        self.assertEqual(len(json.loads(response.body)), 1)
        self.assertEqual(self.spy.calls["save_env"], [])
        self.assertEqual(self.dirty(), 0)

    def test_a_clear_that_removes_a_rule_still_writes_and_marks(self):
        # The half that must not be lost in the skipping.
        self.set_alert()
        self.quiet()

        response = self.clear_alert("loss")

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), [])
        self.assertEqual(self.spy.calls["save_env"], ["main"])
        self.assertEqual(self.dirty(), 1)
        self.assertEqual(self.stored_alerts(), [])

    def test_setting_a_rule_writes_and_marks(self):
        self.quiet()

        response = self.set_alert()

        self.assertEqual(response.code, 200)
        self.assertEqual(self.spy.calls["save_env"], ["main"])
        self.assertEqual(self.dirty(), 1)


class TestAlertsReadonly(AlertsTestCase):
    app_kwargs = {"readonly": True}

    def test_reading_the_rules_is_allowed(self):
        response = self.fetch("/experiments/alerts?eid=main")
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), [])

    def test_setting_and_clearing_are_refused(self):
        for response in (self.set_alert(), self.clear_alert("loss")):
            self.assertEqual(response.code, 403)
            self.assertFalse(json.loads(response.body)["success"])
        self.assertEqual(self.stored_alerts(), [])


class TestAlertNotifications(AlertsTestCase):
    def test_a_crossed_threshold_notifies_the_environment(self):
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")

        quiet = self.log_metric(1.0, step=1)
        self.assertEqual(self.notifications(sub), [])

        loud = self.log_metric(2.5, step=2)

        self.assertEqual(quiet.code, 200)
        self.assertEqual(loud.code, 200)
        self.assertEqual(
            self.notifications(sub), ["main: loss is 2.5, > 2.0 at step 2"]
        )
        self.assertEqual(sub.last("notification")["data"]["type"], "warning")

    def test_the_firing_is_recorded_on_the_rule(self):
        self.set_alert(condition="> 2.0")
        self.log_metric(2.5, step=7)

        stored = self.stored_alerts()[0]
        self.assertEqual(stored["fire_count"], 1)
        self.assertEqual(stored["last_fired_step"], 7)
        self.assertIsNotNone(stored["last_fired_at"])

    def test_the_debounce_holds_across_requests(self):
        # Each observation is its own request, so the streak only works
        # because it is read back out of the stored record every time.
        sub = self.subscribe()
        self.set_alert(condition="> 2.0", for_steps=3)

        for step, value in enumerate([2.5, 2.5]):
            self.log_metric(value, step=step)
        self.assertEqual(self.notifications(sub), [])
        self.assertEqual(self.stored_alerts()[0]["streak"], 2)

        self.log_metric(2.5, step=2)

        self.assertEqual(len(self.notifications(sub)), 1)
        self.assertIn("for 3 observations", self.notifications(sub)[0])

    def test_a_metric_that_stays_over_its_threshold_notifies_once(self):
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")

        for step in range(5):
            self.log_metric(2.5, step=step)

        self.assertEqual(len(self.notifications(sub)), 1)
        self.assertEqual(self.stored_alerts()[0]["fire_count"], 1)

    def test_a_diverged_metric_fires_the_nan_rule_and_not_the_threshold(self):
        # ``null`` is what the client actually sends for a diverged metric:
        # standard JSON cannot spell a non-finite number, so visdom's own
        # encoder writes one as null. Posting a float('inf') here instead
        # would be testing a body no visdom client ever produces.
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")
        self.set_alert(condition="nan")

        self.log_metric(None, step=3)

        messages = self.notifications(sub)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0], "main: loss is not a finite number at step 3")
        self.assertEqual([rule["fire_count"] for rule in self.stored_alerts()], [0, 1])

    def test_a_non_finite_number_sent_as_one_fires_it_too(self):
        # Tornado's decoder accepts the Infinity/NaN tokens, so a caller that
        # is not a visdom client can still put one in the body.
        sub = self.subscribe()
        self.set_alert(condition="nan")

        self.log_metric(float("inf"), step=4)

        self.assertEqual(self.notifications(sub), ["main: loss is inf at step 4"])

    def test_an_integer_too_wide_for_a_float_does_not_break_the_request(self):
        # JSON has no bound on integer length, and both the comparison and
        # the conversion behind it raise OverflowError on one this wide. The
        # threshold rule cannot judge it and stays quiet; the 'nan' rule is
        # the one that catches it, because an integer a float cannot hold is
        # a metric whose arithmetic ran away just as an infinity is.
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")
        self.set_alert(condition="nan")

        response = self.log_metric(10**400, step=5)

        self.assertEqual(response.code, 200)
        self.assertEqual(
            self.notifications(sub), ["main: loss is not a finite number at step 5"]
        )

    def test_an_eid_that_is_not_a_string_is_refused_rather_than_raising(self):
        # ``extract_eid`` escapes what it is given, which means calling
        # ``strip`` on it: a JSON number would raise AttributeError out of
        # the handler and answer 500, telling its sender nothing.
        response = self.post_json("/experiments/alerts", {"action": "get", "eid": 42})
        self.assertEqual(response.code, 400)
        self.assertIn("eid", json.loads(response.body)["error"])

    def test_a_stall_watch_fires_on_the_run_that_stopped_improving(self):
        sub = self.subscribe()
        self.set_alert(metric="acc", condition="stalled", patience=2, goal="max")

        for step, value in enumerate([0.1, 0.9, 0.5, 0.5]):
            self.log_metric(value, metric="acc", step=step)

        self.assertEqual(len(self.notifications(sub)), 1)
        self.assertIn("has not improved in 2 observations", self.notifications(sub)[0])
        self.assertIn("best 0.9", self.notifications(sub)[0])

    def test_a_caller_s_own_message_is_what_arrives(self):
        sub = self.subscribe()
        self.set_alert(condition="nan", message="the loss diverged")

        self.log_metric(float("nan"))

        self.assertEqual(self.notifications(sub), ["main: the loss diverged"])

    def test_both_transports_get_the_same_notification(self):
        # Every socket feature has to work in polling mode too, and this one
        # gets that for free: ``notify`` writes one message to whatever is
        # subscribed, so there is nothing transport-shaped in the path.
        websocket = self.subscribe(sid="websocket")
        polling = self.subscribe(sid="polling")
        self.set_alert(condition="> 2.0")

        self.log_metric(2.5, step=1)

        expected = {
            "command": "notification",
            "data": {
                "message": "main: loss is 2.5, > 2.0 at step 1",
                "type": "warning",
            },
        }
        self.assertEqual(websocket.last("notification"), expected)
        self.assertEqual(polling.last("notification"), expected)

    def test_only_the_environment_being_watched_hears_about_it(self):
        watching = self.subscribe(eid="main", sid="watching")
        elsewhere = self.subscribe(eid="other", sid="elsewhere")
        self.set_alert(condition="> 2.0")

        self.log_metric(2.5)

        self.assertEqual(len(self.notifications(watching)), 1)
        self.assertEqual(self.notifications(elsewhere), [])

    def test_a_cleared_rule_stops_notifying(self):
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")
        self.clear_alert("loss")

        self.log_metric(2.5)

        self.assertEqual(self.notifications(sub), [])

    def test_a_refused_observation_notifies_nothing(self):
        # The rule is folded inside the mutation and the toast is sent after
        # the write is on its way, so a request the store refuses leaves
        # neither a notification nor a recorded streak behind.
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")
        self.log_metric(1.0)
        self.post_json(
            "/experiments/log",
            {"action": "finish", "eid": "main", "status": "finished"},
        )

        refused = self.log_metric(2.5)

        self.assertEqual(refused.code, 409)
        self.assertEqual(self.notifications(sub), [])
        self.assertEqual(self.stored_alerts()[0]["streak"], 0)

    def test_an_environment_with_no_rules_logs_metrics_as_before(self):
        sub = self.subscribe()
        response = self.log_metric(2.5)

        self.assertEqual(response.code, 200)
        self.assertEqual(self.notifications(sub), [])
        # A 200 and a silent socket are also what dropping the observation
        # would look like, so the point of this test is the third assertion:
        # the metric reached the record the way it does without any rules.
        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment("main")
        self.assertEqual(experiment.latest_metric("loss").value, 2.5)


class TestAWriteThatFails(AlertsTestCase):
    """What a rule is left holding when the save behind it raises.

    The fold runs on the loop and the write of what it produced runs off it,
    which leaves one window in which an observation can be judged and then not
    persisted. The rules are the only part of the record that cannot be put
    right by sending the request again: a streak that completed has fired, and
    ``observe`` fires on the streak reaching ``for_steps`` exactly, so a
    streak left standing at ``for_steps`` goes on counting without ever firing
    again. The notification would be gone rather than merely late.
    """

    def get_app(self):
        with mock.patch("visdom.server.app.JSONStore", SpyStore):
            app = super().get_app()
        self.spy = app.storage
        self.breaking = None
        real_save = self.spy.save_env

        def save_env(eid, env_data):
            if self.breaking is not None:
                breaking, self.breaking = self.breaking, None
                breaking()
                raise OSError("no space left on device")
            return real_save(eid, env_data)

        self.spy.save_env = save_env
        return app

    def break_next_save(self, during=lambda: None):
        """Make the next env save raise, running ``during`` just before it does.

        ``during`` stands in for another request changing the same rules while
        this one is off the loop waiting on its write. It runs on the storage
        worker rather than on the loop, which is where the loop would be
        running it from: parked on this very await, with nothing of its own to
        do until the write comes back.
        """
        self.breaking = during

    def live_alerts(self, eid="main"):
        """The rules on the environment the server is serving, not on disk."""
        return [rule["key"] for rule in json.loads(self.fetch_rules(eid).body)]

    def fetch_rules(self, eid="main"):
        return self.fetch("/experiments/alerts?eid={0}".format(eid))

    def test_a_failed_metric_save_puts_the_streak_back(self):
        sub = self.subscribe()
        self.set_alert(condition="> 2.0")

        self.break_next_save()
        failed = self.log_metric(2.5, step=1)

        self.assertEqual(failed.code, 500)
        self.assertEqual(self.notifications(sub), [])
        self.assertEqual(json.loads(self.fetch_rules().body)[0]["streak"], 0)

        # the retry the 500 asks for, and the notification it was owed
        retried = self.log_metric(2.5, step=1)

        self.assertEqual(retried.code, 200)
        self.assertEqual(len(self.notifications(sub)), 1)
        self.assertEqual(self.stored_alerts()[0]["fire_count"], 1)

    def test_a_failed_first_rule_is_not_left_on_the_environment(self):
        # The environment had no record at all, so there is no earlier rule
        # list to go back to -- and a rule left in memory regardless would be
        # read back by the next GET and folded by the next metric, with
        # nothing on disk having ever heard of it.
        sub = self.subscribe()
        self.break_next_save()
        failed = self.set_alert(condition="> 2.0")

        self.assertEqual(failed.code, 500)
        self.assertEqual(self.live_alerts(), [])
        self.assertEqual(self.stored_alerts(), [])

        logged = self.log_metric(2.5)

        self.assertEqual(logged.code, 200)
        self.assertEqual(self.notifications(sub), [])

    def test_a_failed_save_leaves_an_earlier_rule_alone(self):
        # The case the rollback is for: a record that already had rules goes
        # back to having exactly those.
        self.set_alert(metric="loss", condition="> 2.0")

        self.break_next_save()
        failed = self.set_alert(metric="accuracy", condition="< 0.5")

        self.assertEqual(failed.code, 500)
        self.assertEqual(self.live_alerts(), ["loss"])
        self.assertEqual([r["key"] for r in self.stored_alerts()], ["loss"])

    def test_a_failed_save_does_not_revert_a_rule_set_in_the_meantime(self):
        self.set_alert(metric="loss", condition="> 2.0")

        def another_request_sets_one():
            blob = self._app.server_state.state["main"]["experiment"]
            blob["alerts"] = blob["alerts"] + [
                {"key": "accuracy", "condition": "<", "threshold": 0.5}
            ]

        self.break_next_save(during=another_request_sets_one)
        failed = self.log_metric(2.5, step=1)

        # The other request has already been answered with a 200, so its rule
        # has to still be there. Rolling back over it would take a stored rule
        # out of the environment the server is serving to put this request's
        # streak back, and the next write of that environment would persist
        # the version without it.
        self.assertEqual(failed.code, 500)
        self.assertEqual(self.live_alerts(), ["loss", "accuracy"])
