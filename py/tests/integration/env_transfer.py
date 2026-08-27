#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Moving environments in and out of the server over HTTP.

Five routes carry an environment across the wire rather than building one pane
at a time: ``/upload_env`` takes an exported dashboard back in, ``/fork_env``
copies one, ``/save`` writes it out, ``/env_state`` reads it back, and
``/win_data`` is the raw get/set escape hatch beneath all of them. Their happy
paths are exercised elsewhere; what is pinned here is the input handling, since
every one of them accepts a body a browser did not build.

``/upload_env``'s 100 MB ceiling is deliberately not exercised: the limit is a
local inside ``post()``, so proving it would mean pushing an actual 100 MB body
through the in-process server for one assertion.
"""

import json
import os
import uuid

import pytest

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import env_payload

pytestmark = pytest.mark.integration

BOUNDARY = "----VisdomTestBoundary"


def _multipart(filename, body, field="file"):
    """Encode one file part exactly as the dashboard's upload form does."""
    if isinstance(body, str):
        body = body.encode()
    head = (
        '--{0}\r\nContent-Disposition: form-data; name="{1}"; filename="{2}"\r\n'
        "Content-Type: application/json\r\n\r\n".format(BOUNDARY, field, filename)
    )
    tail = "\r\n--{0}--\r\n".format(BOUNDARY)
    return head.encode() + body + tail.encode()


class UploadTestCase(VisdomHTTPTestCase):
    """Shared upload plumbing: post a file part and decode the JSON reply."""

    def upload(self, filename, body, field="file"):
        return self.fetch(
            "/upload_env",
            method="POST",
            body=_multipart(filename, body, field=field),
            headers={
                "Content-Type": "multipart/form-data; boundary={0}".format(BOUNDARY)
            },
        )

    def upload_json(self, filename, payload, field="file"):
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        resp = self.upload(filename, body, field=field)
        return resp, json.loads(resp.body)

    def exported_env(self, content="uploaded pane"):
        return env_payload(
            jsons={"w1": {"id": "w1", "type": "text", "content": content}}
        )


class TestUploadEnvSuccess(UploadTestCase):
    def test_a_valid_export_is_accepted(self):
        resp, body = self.upload_json("run.json", self.exported_env())
        self.assertEqual(resp.code, 200)
        self.assertTrue(body["success"])
        self.assertIn(body["eid"], body["message"])

    def test_the_uploaded_panes_land_in_the_environment(self):
        _, body = self.upload_json("run.json", self.exported_env("hello"))
        self.assertEqual(self.get_win_data("w1", eid=body["eid"])["content"], "hello")

    def test_the_uploaded_env_is_listed(self):
        _, body = self.upload_json("run.json", self.exported_env())
        self.assertIn(body["eid"], self.get_envs())

    def test_the_uploaded_env_is_persisted(self):
        _, body = self.upload_json("run.json", self.exported_env())
        saved = os.path.join(self.env_path, "{0}.json".format(body["eid"]))
        self.assertTrue(os.path.isfile(saved))

    def test_the_reload_settings_come_across_too(self):
        payload = env_payload(jsons={}, reload={"width": 300})
        _, body = self.upload_json("run.json", payload)
        self.assertEqual(self._app.state[body["eid"]]["reload"], {"width": 300})


class TestUploadEnvNaming(UploadTestCase):
    """The new id is derived from the filename, but is never allowed to collide."""

    def _uid(self, eid, prefix):
        self.assertTrue(eid.startswith(prefix))
        return eid[len(prefix) :]

    def test_the_filename_becomes_part_of_the_id(self):
        _, body = self.upload_json("resnet.json", self.exported_env())
        uid = self._uid(body["eid"], "uploaded_resnet_")
        self.assertEqual(len(uid), 8)
        uuid.UUID(hex=uid + "0" * 24)

    def test_a_non_json_filename_contributes_no_name(self):
        _, body = self.upload_json("resnet.txt", self.exported_env())
        self.assertEqual(len(self._uid(body["eid"], "uploaded_")), 8)

    def test_an_export_named_main_does_not_become_main(self):
        """``main`` is the server's own env; an upload must never land on it."""
        _, body = self.upload_json("main.json", self.exported_env())
        self.assertEqual(len(self._uid(body["eid"], "uploaded_")), 8)
        self.assertNotIn("main", self.get_win_data(eid="main"))

    def test_a_path_in_the_filename_is_reduced_to_its_basename(self):
        _, body = self.upload_json("/etc/passwd/run.json", self.exported_env())
        self.assertTrue(body["eid"].startswith("uploaded_run_"))

    def test_separators_in_the_name_are_escaped(self):
        _, body = self.upload_json("a\\b.json", self.exported_env())
        self.assertTrue(body["eid"].startswith("uploaded_a_b_"))
        self.assertNotIn("\\", body["eid"])

    def test_two_uploads_of_one_file_do_not_overwrite_each_other(self):
        _, first = self.upload_json("run.json", self.exported_env("first"))
        _, second = self.upload_json("run.json", self.exported_env("second"))
        self.assertNotEqual(first["eid"], second["eid"])
        self.assertEqual(self.get_win_data("w1", eid=first["eid"])["content"], "first")


class TestUploadEnvRejections(UploadTestCase):
    def test_a_request_with_no_file_part_is_rejected(self):
        resp = self.post_json("/upload_env", {})
        self.assertEqual(resp.code, 400)
        self.assertIn("No file", json.loads(resp.body)["error"])

    def test_a_file_under_another_field_name_is_not_read(self):
        resp, body = self.upload_json(
            "run.json", self.exported_env(), field="dashboard"
        )
        self.assertEqual(resp.code, 400)
        self.assertFalse(body["success"])

    def test_a_file_that_is_not_json_is_rejected(self):
        resp, body = self.upload_json("run.json", "{not json")
        self.assertEqual(resp.code, 400)
        self.assertIn("Invalid JSON", body["error"])

    def test_json_that_is_not_an_object_is_rejected(self):
        resp, body = self.upload_json("run.json", "[1, 2, 3]")
        self.assertEqual(resp.code, 400)
        self.assertIn("Visdom JSON", body["error"])

    def test_an_object_without_jsons_is_rejected(self):
        resp, body = self.upload_json("run.json", {"reload": {}})
        self.assertEqual(resp.code, 400)
        self.assertIn("Visdom JSON", body["error"])

    def test_an_object_without_reload_is_rejected(self):
        resp, body = self.upload_json("run.json", {"jsons": {}})
        self.assertEqual(resp.code, 400)
        self.assertIn("Visdom JSON", body["error"])

    def test_a_rejected_upload_creates_no_environment(self):
        before = set(self.get_envs())
        self.upload_json("run.json", "{not json")
        self.assertEqual(set(self.get_envs()), before)


class TestForkEnvTransfer(VisdomHTTPTestCase):
    def test_the_new_id_is_returned(self):
        self.create_text_window(eid="src")
        resp = self.post_json("/fork_env", {"prev_eid": "src", "eid": "dst"})
        self.assertEqual(resp.body.decode(), "dst")

    def test_the_fork_is_written_to_disk_immediately(self):
        """Unlike a normal window write, forking persists without a ``/save``."""
        self.create_text_window(eid="src")
        self.post_json("/fork_env", {"prev_eid": "src", "eid": "dst"})
        self.assertTrue(os.path.isfile(os.path.join(self.env_path, "dst.json")))

    def test_the_target_id_is_escaped(self):
        self.create_text_window(eid="src")
        resp = self.post_json("/fork_env", {"prev_eid": "src", "eid": "a/b"})
        self.assertEqual(resp.body.decode(), "a_b")
        self.assertIn("a_b", self.get_envs())

    def test_the_source_id_is_escaped_before_it_is_looked_up(self):
        self.create_text_window(eid="a_b")
        resp = self.post_json("/fork_env", {"prev_eid": "a/b", "eid": "dst"})
        self.assertEqual(resp.code, 200)

    def test_forking_onto_an_existing_env_replaces_it(self):
        self.create_text_window(eid="src", content="source")
        self.create_text_window(eid="dst", content="target")
        self.post_json("/fork_env", {"prev_eid": "src", "eid": "dst"})
        panes = self.get_win_data(eid="dst")
        self.assertEqual([p["content"] for p in panes.values()], ["source"])


class TestSaveEnvTransfer(VisdomHTTPTestCase):
    def test_the_written_ids_are_reported_back(self):
        self.create_text_window(eid="keep")
        self.assertEqual(json.loads(self.save(["keep"]).body), ["keep"])

    def test_ids_are_escaped_before_they_become_filenames(self):
        self.create_text_window(eid="a_b")
        self.save(["a/b"])
        self.assertTrue(os.path.isfile(os.path.join(self.env_path, "a_b.json")))

    def test_an_unknown_env_is_skipped_rather_than_created(self):
        self.assertEqual(json.loads(self.save(["ghost"]).body), [])
        self.assertFalse(os.path.isfile(os.path.join(self.env_path, "ghost.json")))

    def test_a_body_without_data_is_an_unhandled_error(self):
        """Documents today's contract: the missing key surfaces as a 500.

        Every sibling route validates its body and answers 400. ``/save`` reads
        ``args["data"]`` straight, so a body without it is a server error rather
        than a client one. Pinned so that fixing it is a visible change.
        """
        self.assertEqual(self.post_json("/save", {}).code, 500)


class TestEnvStateTransfer(VisdomHTTPTestCase):
    def test_an_unknown_env_is_a_not_found(self):
        resp = self.post_json("/env_state", {"eid": "ghost"})
        self.assertEqual(resp.code, 404)
        self.assertIn("ghost", json.loads(resp.body)["error"])

    def test_a_known_env_returns_its_panes(self):
        win = self.create_text_window(eid="one", content="hi")
        panes = json.loads(self.post_json("/env_state", {"eid": "one"}).body)
        self.assertEqual(panes[win]["content"], "hi")

    def test_the_id_is_escaped_before_it_is_looked_up(self):
        self.create_text_window(eid="a_b")
        self.assertEqual(self.post_json("/env_state", {"eid": "a/b"}).code, 200)

    def test_a_non_string_id_is_coerced_before_lookup(self):
        self.assertEqual(self.post_json("/env_state", {"eid": 7}).code, 404)

    def test_no_id_lists_every_environment(self):
        self.create_text_window(eid="one")
        self.assertEqual(sorted(self.get_envs()), ["main", "one"])


class TestWinDataTransfer(VisdomHTTPTestCase):
    """``/win_data`` reads panes with a body, and writes them with ``data``."""

    def _set(self, payload, eid="main", win=None):
        body = {"eid": eid, "win": win, "data": json.dumps(payload)}
        return self.post_json("/win_data", body)

    def test_a_whole_environment_can_be_written_at_once(self):
        self._set({"w1": {"id": "w1", "type": "text", "content": "set"}})
        self.assertEqual(self.get_win_data("w1")["content"], "set")

    def test_a_single_pane_can_be_written(self):
        self.create_text_window(win="w1", content="first")
        self._set({"id": "w2", "type": "text", "content": "second"}, win="w2")
        self.assertEqual(self.get_win_data("w1")["content"], "first")
        self.assertEqual(self.get_win_data("w2")["content"], "second")

    def test_writing_creates_the_environment_if_it_is_new(self):
        self._set({"w1": {"id": "w1", "type": "text", "content": "x"}}, eid="fresh")
        self.assertIn("fresh", self.get_envs())

    def test_a_write_replaces_the_panes_it_does_not_mention(self):
        self.create_text_window(win="old")
        self._set({"w1": {"id": "w1", "type": "text", "content": "x"}})
        self.assertEqual(list(self.get_win_data().keys()), ["w1"])

    def test_reading_an_unknown_pane_is_a_bad_request(self):
        resp = self.post_json("/win_data", {"eid": "main", "win": "ghost"})
        self.assertEqual(resp.code, 400)

    def test_reading_a_whole_environment_returns_every_pane(self):
        first = self.create_text_window()
        second = self.create_text_window()
        self.assertEqual(sorted(self.get_win_data()), sorted([first, second]))
