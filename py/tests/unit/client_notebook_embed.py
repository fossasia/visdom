#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for embedding the dashboard in a notebook cell.

``Visdom.show`` builds an iframe and nothing more -- no request is made and
IPython is never imported -- so the whole contract is the markup it returns and
the URL inside it. Nothing here reaches outside the client -- no server is
started, and no request is made.
"""

import logging

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


class TestDashboardUrl:
    def test_it_deep_links_to_the_clients_own_env(self):
        assert _client(env="run-7")._dashboard_url() == (
            "http://localhost:8097/env/run-7"
        )

    def test_an_explicit_env_wins(self):
        assert _client(env="run-7")._dashboard_url("other") == (
            "http://localhost:8097/env/other"
        )

    def test_the_base_url_is_kept(self):
        client = _client(base_url="/visdom")

        assert client._dashboard_url() == "http://localhost:8097/visdom/env/main"

    def test_the_env_is_percent_encoded(self):
        # The route is '/env/(.*)' and the frontend decodeURIComponent's what it
        # finds there, so a space has to arrive encoded rather than raw.
        client = _client(env="run 7")

        assert client._dashboard_url() == "http://localhost:8097/env/run%207"

    def test_the_env_is_normalized_the_way_the_server_keys_it(self):
        # A slash would otherwise read as another path segment, and the env it
        # named would not be the one the server stored.
        client = _client()

        assert client._dashboard_url("sweep/trial 1") == (
            "http://localhost:8097/env/sweep_trial%201"
        )
        assert client._dashboard_url(" padded ") == ("http://localhost:8097/env/padded")

    def test_a_remote_server_keeps_its_own_host(self):
        client = _client(server="https://visdom.example.com", port=443)

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"


class TestShow:
    def test_it_renders_an_iframe_at_the_dashboard_url(self):
        html = _client(env="run-7").show()._repr_html_()

        assert 'src="http://localhost:8097/env/run-7"' in html
        assert html.startswith("<iframe ")

    def test_the_default_size_is_600px_tall_and_full_width(self):
        html = _client().show()._repr_html_()

        assert "width:100%" in html
        assert "height:600px" in html

    def test_the_sizes_are_css_and_not_html_dimension_attributes(self):
        # The HTML width=/height= attributes are a legacy length: they read
        # '40vh' as 40 pixels and drop the unit, so a documented CSS dimension
        # would silently come out the wrong size.
        html = _client().show(height="40vh", width=480)._repr_html_()

        assert 'style="width:480px;height:40vh;border:0"' in html
        assert "height=" not in html
        assert "width=" not in html

    def test_a_dimension_is_escaped_before_it_reaches_the_attribute(self):
        # Dimensions are interpolated into markup, so a string one is untrusted
        # input even though it is the caller's own.
        html = _client().show(width='100%" onload="alert(1)')._repr_html_()

        assert 'onload="alert(1)' not in html
        assert "&quot;" in html

    def test_a_second_css_declaration_is_refused(self):
        # A dimension is a length. Anything past a semicolon would be styling
        # the notebook rather than sizing the frame.
        with pytest.raises(ValueError):
            _client().show(height="600px;position:fixed;top:0")

    def test_an_empty_dimension_is_refused(self):
        with pytest.raises(ValueError):
            _client().show(width="   ")

    def test_a_nonpositive_dimension_is_refused(self):
        # From the show() call, not from whatever displays its result later.
        with pytest.raises(ValueError):
            _client().show(height=0)

    def test_the_client_itself_renders_the_same_iframe(self):
        client = _client(env="run-7")

        assert client._repr_html_() == client.show()._repr_html_()

    def test_outside_a_notebook_it_prints_the_url(self):
        assert repr(_client(env="run-7").show()) == ("http://localhost:8097/env/run-7")


class TestOffline:
    def test_an_offline_client_has_no_server_to_embed(self):
        embed = _client(offline=True).show()

        assert embed.url is None
        assert "offline" in embed._repr_html_()
        assert "<iframe" not in embed._repr_html_()

    def test_the_note_is_what_it_prints(self):
        embed = _client(offline=True).show()

        assert repr(embed) == embed.note


class TestCredentials:
    def test_a_password_in_the_server_url_never_reaches_the_markup(self):
        # show()'s output is saved in the notebook and shared with it.
        client = _client(server="https://user:hunter2@visdom.example.com", port=443)

        html = client.show()._repr_html_()

        assert client._dashboard_url() == "https://visdom.example.com:443/env/main"
        assert "hunter2" not in html
        assert "hunter2" not in repr(client.show())

    def test_a_host_without_credentials_is_left_exactly_as_it_is(self):
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
    def test_a_workspace_client_is_told_the_frame_will_not_be_scoped(self, caplog):
        # The browser cannot send X-Visdom-Workspace, so the frame shows the
        # server's default view. Silently showing the wrong data is the thing
        # to avoid; the URL itself is still the best one available.
        client = _client(workspace="team-7")

        with caplog.at_level(logging.WARNING, logger="visdom"):
            embed = client.show()

        assert "team-7" in caplog.text
        assert embed.url == "http://localhost:8097/env/main"

    def test_an_unscoped_client_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="visdom"):
            _client().show()

        assert caplog.text == ""
