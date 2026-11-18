#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the ``%visdom`` line magic.

The magic is a command line and no IPython: parse the line, build the client
that names the environment, and hand back the iframe ``Visdom.show`` builds.
All three are covered here with the client replaced, so nothing in this file
listens on a port.

The one test that does spawn is the import guard, which has to measure a clean
interpreter and so runs in a subprocess.
"""

import os
import subprocess
import sys
import textwrap

import pytest

import visdom
from visdom import notebook

pytestmark = pytest.mark.unit


class _FakeShell:
    """Stands in for the IPython shell handed to the extension entry point."""

    def __init__(self):
        self.magics_manager = type("_Manager", (), {"magics": {"line": {}}})()

    def register_magic_function(self, func, kind, name):
        self.magics_manager.magics.setdefault(kind, {})[name] = func


class _FakeEmbed:
    def __init__(self, client, height, width):
        self.client = client
        self.height = height
        self.width = width


class _FakeVisdom:
    """Records how the magic built its client, and what it asked show() for."""

    built = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeVisdom.built.append(self)

    def show(self, height=600, width="100%"):
        return _FakeEmbed(self, height, width)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No real client, and no state carried between tests."""
    notebook._clients.clear()
    _FakeVisdom.built = []
    monkeypatch.setattr(notebook, "Visdom", _FakeVisdom)
    yield
    notebook._clients.clear()


def _parse(line=""):
    return notebook._build_parser().parse_args(line.split())


class TestParsing:
    def test_the_defaults_are_a_local_server_on_8097(self):
        args = _parse()

        assert (args.server, args.port) == ("http://localhost", 8097)
        assert (args.env, args.height, args.width) == ("main", 600, "100%")

    def test_it_takes_a_port_and_an_env(self):
        args = _parse("--port 9000 --env run-7")

        assert (args.port, args.env) == (9000, "run-7")

    def test_an_env_can_be_quoted(self):
        args = notebook._build_parser().parse_args(["--env", "run 7"])

        assert args.env == "run 7"

    def test_a_numeric_dimension_is_pixels_and_anything_else_is_css(self):
        args = _parse("--height 400 --width 40vh")

        assert args.height == 400
        assert args.width == "40vh"

    @pytest.mark.parametrize("line", ["--port 0", "--port 99999", "--port eight"])
    def test_an_impossible_port_is_a_usage_error(self, line):
        with pytest.raises(ValueError):
            _parse(line)

    def test_a_nonpositive_dimension_is_a_usage_error(self):
        with pytest.raises(ValueError):
            _parse("--height 0")

    @pytest.mark.parametrize(
        "line,wanted",
        [
            ("--port 99999", "between 1 and 65535"),
            ("--port eight", "port must be a number"),
            ("--height 0", "must be positive"),
        ],
    )
    def test_a_bad_value_is_explained_rather_than_named(self, line, wanted):
        # argparse keeps an ArgumentTypeError's message but replaces a
        # ValueError's with "invalid _port value: ...", which leaks the
        # converter's own name and loses the explanation.
        with pytest.raises(ValueError, match=wanted):
            _parse(line)

    def test_an_unknown_flag_does_not_end_the_kernel(self):
        # argparse would answer this with SystemExit, which in a notebook reads
        # as a crashed kernel rather than a typo.
        with pytest.raises(ValueError, match="--logdir"):
            _parse("--logdir runs")

    def test_help_is_returned_rather_than_raised(self):
        printed = notebook.visdom_magic("--help")

        assert "%visdom" in printed
        assert "--env" in printed
        assert _FakeVisdom.built == []


class TestServerUrl:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("http://localhost", "http://localhost"),
            ("localhost", "http://localhost"),
            ("gpu-box.example.com", "http://gpu-box.example.com"),
            ("https://visdom.example.com", "https://visdom.example.com"),
            ("http://localhost/", "http://localhost"),
            ("http://localhost/ignored", "http://localhost"),
        ],
    )
    def test_it_is_shaped_the_way_the_client_keeps_it(self, given, expected):
        # The port is appended to this, so anything after the host would land
        # in the middle of the url.
        assert notebook._normalize_server(given) == expected


class TestEmbedding:
    def test_the_dashboard_is_embedded_in_the_cell(self):
        embed = notebook.visdom_magic("--env run-7 --height 400")

        assert embed.height == 400
        assert embed.client.kwargs["env"] == "run-7"

    def test_the_client_is_built_for_the_env_that_was_asked_for(self):
        notebook.visdom_magic("--env run-7 --port 9000")

        kwargs = _FakeVisdom.built[0].kwargs
        assert kwargs["env"] == "run-7"
        assert kwargs["port"] == 9000
        assert kwargs["server"] == "http://localhost"

    def test_building_the_client_is_what_registers_the_env(self):
        # The client's POST is what creates the env, and it is for that and
        # the URL, not for plotting: no socket, so no reader thread left behind.
        notebook.visdom_magic("--env run-7")

        assert _FakeVisdom.built[0].kwargs["use_incoming_socket"] is False

    def test_the_real_constructor_posts_the_registration_the_magic_relies_on(
        self, monkeypatch
    ):
        # The assertion above is about the magic; this one is about the claim
        # underneath it. With the fake client in place, the magic would go on
        # embedding a link to an unregistered env if Visdom ever stopped
        # sending this, so the real constructor is driven here with only its
        # transport replaced.
        posted = []

        def record(self, url, data=None):
            posted.append(url)
            return ""

        monkeypatch.setattr(visdom.Visdom, "_handle_post", record)

        visdom.Visdom(
            server="http://localhost",
            port=8097,
            env="run 7",
            use_incoming_socket=False,
        )

        assert posted == ["http://localhost:8097/env/run 7"]

    def test_a_server_without_a_scheme_still_names_a_host(self):
        notebook.visdom_magic("--server localhost")

        assert _FakeVisdom.built[0].kwargs["server"] == "http://localhost"

    def test_the_iframe_size_is_passed_through(self):
        embed = notebook.visdom_magic("--height 40vh --width 480")

        assert (embed.height, embed.width) == ("40vh", 480)

    def test_a_quoted_env_reaches_the_client_whole(self):
        # Through the magic rather than through the parser: the line is
        # tokenized with shlex, and a plain split() would hand the client
        # 'run' and leave '7"' as a stray argument.
        notebook.visdom_magic('--env "run 7"')

        assert _FakeVisdom.built[0].kwargs["env"] == "run 7"

    def test_re_running_the_cell_reuses_the_one_client(self):
        # Every Visdom starts a session reaper that loops for the life of the
        # process and holds its client while it does, so a second client per
        # execution is a thread per execution that never goes away.
        first = notebook.visdom_magic("--env run-7")
        again = notebook.visdom_magic("--env run-7")

        assert again.client is first.client
        assert len(_FakeVisdom.built) == 1

    def test_a_different_env_gets_its_own_client(self):
        # The registration is per-env, and it happens in the constructor.
        notebook.visdom_magic("--env run-7")
        notebook.visdom_magic("--env run-8")

        assert [built.kwargs["env"] for built in _FakeVisdom.built] == [
            "run-7",
            "run-8",
        ]


class TestExtension:
    def test_load_ext_registers_the_line_magic(self):
        shell = _FakeShell()

        notebook.load_ipython_extension(shell)

        assert shell.magics_manager.magics["line"]["visdom"] is notebook.visdom_magic

    def test_unload_ext_takes_it_back(self):
        shell = _FakeShell()
        notebook.load_ipython_extension(shell)

        notebook.unload_ipython_extension(shell)

        assert "visdom" not in shell.magics_manager.magics["line"]

    def test_unloading_twice_is_not_an_error(self):
        shell = _FakeShell()

        notebook.unload_ipython_extension(shell)
        notebook.unload_ipython_extension(shell)

    def test_a_shell_without_a_magics_manager_is_tolerated(self):
        notebook.unload_ipython_extension(object())


def test_the_magic_costs_nothing_until_it_is_loaded():
    """``import visdom`` must not reach this module, and it must not need IPython.

    The magic is registered against the shell IPython hands the extension entry
    point, so IPython is a notebook's dependency rather than visdom's. A fresh
    interpreter is the only thing that can answer either question, because by
    now this test module has imported both.
    """
    probe = textwrap.dedent(
        """
        import sys
        import visdom
        print("notebook" if "visdom.notebook" in sys.modules else "")
        import visdom.notebook
        print("IPython" if "IPython" in sys.modules else "")
        """
    )
    env = dict(os.environ)
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(visdom.__file__)))
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == [], "pulled in " + " ".join(done.stdout.split())
