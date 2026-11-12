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
    for name, value in kwargs.items():
        setattr(client, name, value)
    return client


class _ColabOutput:
    """Stands in for ``google.colab.output``."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def eval_js(self, script):
        self.calls.append(script)
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

        assert 'height="600"' in html
        assert 'width="100%"' in html

    def test_a_number_is_pixels_and_a_string_is_css(self, no_colab):
        html = _client().show(height="40vh", width=480)._repr_html_()

        assert 'height="40vh"' in html
        assert 'width="480"' in html

    def test_a_dimension_is_escaped_before_it_reaches_the_attribute(self, no_colab):
        # Dimensions are interpolated into markup, so a string one is untrusted
        # input even though it is the caller's own.
        html = _client().show(width='100%" onload="alert(1)')._repr_html_()

        assert 'onload="alert(1)' not in html
        assert "&quot;" in html

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

    def test_a_failed_proxy_lookup_falls_back_to_the_plain_url(self, monkeypatch):
        # eval_js raises for everything from a detached frontend to a timeout,
        # and none of that should cost the caller an iframe.
        output = _ColabOutput(error=RuntimeError("no frontend"))
        monkeypatch.setattr(visdom, "_colab_output", lambda: output)

        assert _client()._dashboard_url() == "http://localhost:8097/env/main"

    def test_a_proxy_that_answers_with_junk_is_ignored(self, monkeypatch):
        monkeypatch.setattr(visdom, "_colab_output", lambda: _ColabOutput(result=""))

        assert _client()._dashboard_url() == "http://localhost:8097/env/main"


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
