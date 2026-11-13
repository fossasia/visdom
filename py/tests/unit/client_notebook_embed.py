#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for embedding the dashboard in a notebook cell.

``Visdom.show`` builds an iframe and nothing more -- no request is made and
IPython is never imported -- so the whole contract is the markup it returns and
the URL inside it. The Colab branch is the only part that reaches outside the
client, and it reaches through ``_colab_output``, which these tests replace.
"""

import logging
import sys
from types import SimpleNamespace

import pytest

import visdom
from visdom import Visdom

pytestmark = pytest.mark.unit


def _client(env="main", server="http://localhost", port=8097, base_url="", **kwargs):
    client = Visdom.__new__(Visdom)
    client.env = env
    client.server = server
    client.port = port
    client.base_url = base_url
    client.offline = False
    client.workspace = None
    for name, value in kwargs.items():
        setattr(client, name, value)
    return client


class _ColabOutput:
    """Stands in for ``google.colab.output``."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.timeouts = []

    def eval_js(self, script, timeout_sec=None):
        self.calls.append(script)
        self.timeouts.append(timeout_sec)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def no_colab(monkeypatch):
    monkeypatch.setattr(visdom, "_colab_output", lambda: None)


class TestDashboardUrl:
    def test_it_deep_links_to_the_clients_own_env(self, no_colab):
        assert _client(env="run-7")._dashboard_url() == (
            "http://localhost:8097/env/run-7"
        )

    def test_an_explicit_env_wins(self, no_colab):
        assert _client(env="run-7")._dashboard_url("other") == (
            "http://localhost:8097/env/other"
        )

    def test_the_base_url_is_kept(self, no_colab):
        client = _client(base_url="/visdom")

        assert client._dashboard_url() == "http://localhost:8097/visdom/env/main"

    def test_the_env_is_percent_encoded(self, no_colab):
        # The route is '/env/(.*)' and the frontend decodeURIComponent's what it
        # finds there, so a space has to arrive encoded rather than raw.
        client = _client(env="run 7")

        assert client._dashboard_url() == "http://localhost:8097/env/run%207"

    def test_the_env_is_normalized_the_way_the_server_keys_it(self, no_colab):
        # A slash would otherwise read as another path segment, and the env it
        # named would not be the one the server stored.
        client = _client()

        assert client._dashboard_url("sweep/trial 1") == (
            "http://localhost:8097/env/sweep_trial%201"
        )
        assert client._dashboard_url(" padded ") == ("http://localhost:8097/env/padded")

    def test_a_remote_server_keeps_its_own_host(self, no_colab):
        client = _client(server="https://visdom.example.com", port=443)

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"


class TestShow:
    def test_it_renders_an_iframe_at_the_dashboard_url(self, no_colab):
        html = _client(env="run-7").show()._repr_html_()

        assert 'src="http://localhost:8097/env/run-7"' in html
        assert html.startswith("<iframe ")

    def test_the_default_size_is_600px_tall_and_full_width(self, no_colab):
        html = _client().show()._repr_html_()

        assert "width:100%" in html
        assert "height:600px" in html

    def test_the_sizes_are_css_and_not_html_dimension_attributes(self, no_colab):
        # The HTML width=/height= attributes are a legacy length: they read
        # '40vh' as 40 pixels and drop the unit, so a documented CSS dimension
        # would silently come out the wrong size.
        html = _client().show(height="40vh", width=480)._repr_html_()

        assert 'style="width:480px;height:40vh;border:0"' in html
        assert "height=" not in html
        assert "width=" not in html

    def test_a_dimension_is_escaped_before_it_reaches_the_attribute(self, no_colab):
        # Dimensions are interpolated into markup, so a string one is untrusted
        # input even though it is the caller's own.
        html = _client().show(width='100%" onload="alert(1)')._repr_html_()

        assert 'onload="alert(1)' not in html
        assert "&quot;" in html

    def test_a_second_css_declaration_is_refused(self, no_colab):
        # A dimension is a length. Anything past a semicolon would be styling
        # the notebook rather than sizing the frame.
        with pytest.raises(ValueError):
            _client().show(height="600px;position:fixed;top:0")

    def test_an_empty_dimension_is_refused(self, no_colab):
        with pytest.raises(ValueError):
            _client().show(width="   ")

    def test_a_nonpositive_dimension_is_refused(self, no_colab):
        # From the show() call, not from whatever displays its result later.
        with pytest.raises(ValueError):
            _client().show(height=0)

    def test_the_client_itself_renders_the_same_iframe(self, no_colab):
        client = _client(env="run-7")

        assert client._repr_html_() == client.show()._repr_html_()

    def test_outside_a_notebook_it_prints_the_url(self, no_colab):
        assert repr(_client(env="run-7").show()) == ("http://localhost:8097/env/run-7")


class TestOffline:
    def test_an_offline_client_has_no_server_to_embed(self, no_colab):
        embed = _client(offline=True).show()

        assert embed.url is None
        assert "offline" in embed._repr_html_()
        assert "<iframe" not in embed._repr_html_()

    def test_the_note_is_what_it_prints(self, no_colab):
        embed = _client(offline=True).show()

        assert repr(embed) == embed.note


class TestCredentials:
    def test_a_password_in_the_server_url_never_reaches_the_markup(self, no_colab):
        # show()'s output is saved in the notebook and shared with it.
        client = _client(server="https://user:hunter2@visdom.example.com", port=443)

        html = client.show()._repr_html_()

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"
        assert "hunter2" not in html
        assert "hunter2" not in repr(client.show())

    def test_a_host_without_credentials_is_left_exactly_as_it_is(self, no_colab):
        client = _client(server="https://visdom.example.com", port=443)

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("https://user:pw@host.example.com", "https://host.example.com"),
            ("https://user@host.example.com", "https://host.example.com"),
            ("http://host.example.com:9000", "http://host.example.com:9000"),
            ("http://user:pw@host.example.com:9000", "http://host.example.com:9000"),
            ("http://user:pw@[::1]", "http://[::1]"),
            ("http://localhost", "http://localhost"),
        ],
    )
    def test_only_the_credentials_are_dropped(self, given, expected):
        assert visdom._without_userinfo(given) == expected


class TestWorkspace:
    def test_a_workspace_client_is_told_the_frame_will_not_be_scoped(
        self, no_colab, caplog
    ):
        # The browser cannot send X-Visdom-Workspace, so the frame shows the
        # server's default view. Silently showing the wrong data is the thing
        # to avoid; the URL itself is still the best one available.
        client = _client(workspace="team-7")

        with caplog.at_level(logging.WARNING, logger="visdom"):
            embed = client.show()

        assert "team-7" in caplog.text
        assert embed.url == "http://localhost:8097/env/main"

    def test_an_unscoped_client_says_nothing(self, no_colab, caplog):
        with caplog.at_level(logging.WARNING, logger="visdom"):
            _client().show()

        assert caplog.text == ""


class TestColab:
    def test_a_loopback_server_is_reached_through_the_proxy(self, monkeypatch):
        # Colab serves the notebook from another origin, so 'localhost' in the
        # iframe would resolve against the browser and load nothing.
        output = _ColabOutput(result="https://abc-8097.colab.googleusercontent.com/")
        monkeypatch.setattr(visdom, "_colab_output", lambda: output)

        url = _client(env="run-7", base_url="/visdom")._dashboard_url()

        assert url == ("https://abc-8097.colab.googleusercontent.com/visdom/env/run-7")
        assert output.calls == ["google.colab.kernel.proxyPort(8097)"]

    def test_a_remote_server_is_never_proxied(self, monkeypatch):
        output = _ColabOutput(result="https://abc-8097.colab.googleusercontent.com/")
        monkeypatch.setattr(visdom, "_colab_output", lambda: output)

        client = _client(server="https://visdom.example.com", port=443)

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"
        assert output.calls == []

    def test_the_frontend_is_not_waited_on_forever(self, monkeypatch):
        # eval_js defaults to no deadline. A frontend that went away between
        # cells would hang the display call instead of failing it, and the
        # fallback below would never be reached.
        output = _ColabOutput(result="https://abc-8097.colab.googleusercontent.com/")
        monkeypatch.setattr(visdom, "_colab_output", lambda: output)

        _client()._dashboard_url()

        assert output.timeouts == [visdom.COLAB_PROXY_TIMEOUT]
        assert visdom.COLAB_PROXY_TIMEOUT > 0

    def test_a_failed_proxy_lookup_falls_back_to_the_plain_url(
        self, monkeypatch, caplog
    ):
        # eval_js raises for everything from a detached frontend to a timeout,
        # and none of that should cost the caller an iframe. The fallback URL
        # cannot work from Colab's browser, though, so it is said out loud
        # rather than left as a blank frame with no explanation.
        output = _ColabOutput(error=RuntimeError("no frontend"))
        monkeypatch.setattr(visdom, "_colab_output", lambda: output)

        with caplog.at_level(logging.WARNING, logger="visdom"):
            url = _client()._dashboard_url()

        assert url == "http://localhost:8097/env/main"
        assert "no frontend" in caplog.text
        assert "blank" in caplog.text

    def test_a_proxy_that_answers_with_junk_is_ignored(self, monkeypatch, caplog):
        monkeypatch.setattr(visdom, "_colab_output", lambda: _ColabOutput(result=""))

        with caplog.at_level(logging.WARNING, logger="visdom"):
            url = _client()._dashboard_url()

        assert url == "http://localhost:8097/env/main"
        assert "cannot reach" in caplog.text


class TestColabDetection:
    def test_a_plain_kernel_does_not_import_google_colab(self, monkeypatch):
        # Importing it to find out would be the side effect this avoids: the
        # module is absent outside Colab and present before any cell runs in it.
        monkeypatch.delitem(sys.modules, "google.colab", raising=False)

        assert visdom._colab_output() is None

    def test_the_module_is_used_when_the_kernel_has_it(self, monkeypatch):
        output = _ColabOutput(result="https://proxied.example.com/")
        monkeypatch.setitem(sys.modules, "google", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(output=output))

        assert visdom._colab_output() is output
