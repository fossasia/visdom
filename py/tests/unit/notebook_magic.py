#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the ``%visdom`` line magic.

The magic is three decisions and no IPython: parse the line, decide whether a
server has to be started, and hand back the iframe ``Visdom.show`` builds. All
three are covered here with the network probe, the child process and the client
replaced, so nothing in this file listens on a port or spawns anything.

The one test that does spawn is the import guard, which has to measure a clean
interpreter and so runs in a subprocess.
"""

import os
import subprocess
import sys
import textwrap

import pytest

import requests

import visdom
from visdom import notebook

pytestmark = pytest.mark.unit

# Captured before the fixture below replaces them, so the tests that cover the
# probe and the spawn themselves still reach the real thing.
_real_server_is_up = notebook._server_is_up
_real_start_server = notebook._start_server


class _FakeChild:
    """Stands in for the server subprocess."""

    def __init__(self, alive=True, returncode=0):
        self.alive = alive
        self.returncode = returncode
        self.terminated = 0
        self.killed = 0
        self.waits = []

    def poll(self):
        return None if self.alive else self.returncode

    def terminate(self):
        self.terminated += 1
        self.alive = False

    def kill(self):
        self.killed += 1
        self.alive = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.returncode


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
    """No real probe, no real child, and no state carried between tests."""
    notebook._started.clear()
    _FakeVisdom.built = []
    monkeypatch.setattr(notebook, "Visdom", _FakeVisdom)
    monkeypatch.setattr(
        notebook,
        "_server_is_up",
        lambda *args, **kwargs: pytest.fail("the probe was not replaced"),
    )
    monkeypatch.setattr(
        notebook,
        "_start_server",
        lambda *args, **kwargs: pytest.fail("a server was spawned"),
    )
    yield
    notebook._started.clear()


@pytest.fixture
def server_up(monkeypatch):
    monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: True)


@pytest.fixture
def server_down(monkeypatch):
    monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: False)


def _parse(line=""):
    return notebook._build_parser().parse_args(line.split())


class TestParsing:
    def test_the_defaults_are_a_local_server_on_8097(self):
        args = _parse()

        assert (args.server, args.port, args.base_url) == (
            "http://localhost",
            8097,
            "/",
        )
        assert (args.env, args.height, args.width) == ("main", 600, "100%")
        assert args.no_start is False

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


class TestBaseUrl:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("/", "/"),
            ("", "/"),
            ("visdom", "/visdom"),
            ("/visdom", "/visdom"),
            ("/visdom/", "/visdom"),
            ("  /proxy/8097/  ", "/proxy/8097"),
        ],
    )
    def test_it_is_shaped_the_way_the_client_demands(self, given, expected):
        # Visdom asserts a leading slash and no trailing one, so a base_url
        # typed either way has to be normalized before it reaches the client.
        assert notebook._normalize_base_url(given) == expected


class TestProbe:
    def _record(self, monkeypatch, outcome):
        seen = {}

        def fake_get(url, timeout=None):
            seen["url"] = url
            seen["timeout"] = timeout
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(notebook.requests, "get", fake_get)
        return seen

    def test_any_reply_means_a_server_holds_the_port(self, monkeypatch):
        # A login-enabled server answers the probe with its login form, and a
        # proxy in front of one answers with a redirect; both are "up".
        self._record(monkeypatch, object())

        assert _real_server_is_up("http://localhost", 8097, "/") is True

    def test_a_refused_connection_means_nothing_is_there(self, monkeypatch):
        self._record(monkeypatch, requests.ConnectionError("refused"))

        assert _real_server_is_up("http://localhost", 8097, "/") is False

    def test_a_timeout_means_nothing_is_there(self, monkeypatch):
        self._record(monkeypatch, requests.Timeout("too slow"))

        assert _real_server_is_up("http://localhost", 8097, "/") is False

    def test_the_probe_goes_to_the_dashboard_root(self, monkeypatch):
        seen = self._record(monkeypatch, object())

        _real_server_is_up("http://localhost", 8097, "/")

        assert seen["url"] == "http://localhost:8097/"
        assert seen["timeout"] == notebook.PROBE_TIMEOUT

    def test_a_base_url_is_part_of_the_probe(self, monkeypatch):
        seen = self._record(monkeypatch, object())

        _real_server_is_up("http://localhost", 8097, "/visdom")

        assert seen["url"] == "http://localhost:8097/visdom/"

    def test_a_certificate_this_client_rejects_still_proves_a_server(self, monkeypatch):
        # Something is serving TLS on the port, so starting a second server
        # there would only fail to bind.
        self._record(monkeypatch, requests.exceptions.SSLError("self-signed"))

        assert _real_server_is_up("https://localhost", 8097, "/") is True


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
    def test_a_running_server_is_embedded_without_starting_anything(self, server_up):
        embed = notebook.visdom_magic("--env run-7 --height 400")

        assert embed.height == 400
        assert notebook._started == {}

    def test_the_client_is_built_for_the_env_that_was_asked_for(self, server_up):
        notebook.visdom_magic("--env run-7 --port 9000 --base_url proxy/visdom")

        kwargs = _FakeVisdom.built[0].kwargs
        assert kwargs["env"] == "run-7"
        assert kwargs["port"] == 9000
        assert kwargs["base_url"] == "/proxy/visdom"
        assert kwargs["server"] == "http://localhost"

    def test_building_the_client_is_what_registers_the_env(self, server_up):
        # The client's POST is what creates the env, and it is for that and
        # the URL, not for plotting: no socket, so no reader thread left behind.
        notebook.visdom_magic("--env run-7")

        assert _FakeVisdom.built[0].kwargs["use_incoming_socket"] is False

    def test_a_server_without_a_scheme_still_names_a_host(self, server_up):
        notebook.visdom_magic("--server localhost")

        assert _FakeVisdom.built[0].kwargs["server"] == "http://localhost"

    def test_the_iframe_size_is_passed_through(self, server_up):
        embed = notebook.visdom_magic("--height 40vh --width 480")

        assert (embed.height, embed.width) == ("40vh", 480)


class TestStarting:
    def test_a_missing_local_server_is_started(self, server_down, monkeypatch):
        started = []
        monkeypatch.setattr(
            notebook,
            "_start_server",
            lambda server, port, base_url, timeout: started.append(
                (server, port, base_url, timeout)
            ),
        )

        notebook.visdom_magic("--port 9000 --timeout 5")

        assert started == [("http://localhost", 9000, "/", 5.0)]
        assert len(_FakeVisdom.built) == 1

    def test_no_start_embeds_nothing_and_says_why(self, server_down):
        embed = notebook.visdom_magic("--no-start --port 9000")

        assert embed.url is None
        assert embed.note == (
            "Nothing is answering at http://localhost:9000 and --no-start was "
            "given, so no server was started."
        )
        assert _FakeVisdom.built == []

    def test_a_remote_server_is_never_started_from_here(self, server_down):
        # Spawning a local server for a host the user named would embed the
        # wrong machine's dashboard under the right URL. The note is compared
        # whole: asking whether the host appears somewhere in it would be the
        # substring test CodeQL rejects, and a weaker claim besides.
        embed = notebook.visdom_magic("--server http://gpu-box.example.com --port 9000")

        assert embed.url is None
        assert embed.note == (
            "Nothing is answering at http://gpu-box.example.com:9000. Only a "
            "server on this machine can be started from here, so start it on "
            "that host and run %visdom again."
        )
        assert _FakeVisdom.built == []

    def test_a_loopback_address_counts_as_this_machine(self, server_down):
        assert notebook._refusal_to_start("http://127.0.0.1", 8097, False) is None
        assert notebook._refusal_to_start("http://localhost", 8097, False) is None


class TestSpawning:
    @pytest.fixture
    def spawn(self, monkeypatch, tmp_path):
        log_path = tmp_path / "server.log"
        log_path.write_text("Downloading scripts\nIt's Alive!\n")
        monkeypatch.setattr(notebook, "_server_log", lambda: str(log_path))
        commands = []

        def fake_popen(command, **kwargs):
            commands.append(command)
            return _FakeChild()

        monkeypatch.setattr(notebook.subprocess, "Popen", fake_popen)
        return commands, str(log_path)

    def test_the_server_runs_as_a_child_of_this_interpreter(self, spawn, monkeypatch):
        commands, _ = spawn
        monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: True)

        _real_start_server("http://localhost", 9000, "/", 5)

        assert commands == [[sys.executable, "-m", "visdom.server", "-port", "9000"]]
        assert 9000 in notebook._started

    def test_a_base_url_is_handed_to_the_server_too(self, spawn, monkeypatch):
        commands, _ = spawn
        monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: True)

        _real_start_server("http://localhost", 8097, "/visdom", 5)

        assert commands[0][-2:] == ["-base_url", "/visdom"]

    def test_the_port_is_only_claimed_once(self, spawn, monkeypatch):
        commands, _ = spawn
        monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: True)

        first = _real_start_server("http://localhost", 8097, "/", 5)
        again = _real_start_server("http://localhost", 8097, "/", 5)

        assert again is first
        assert len(commands) == 1

    def test_a_server_that_dies_reports_its_own_output(self, spawn, monkeypatch):
        _, log_path = spawn
        monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: False)
        monkeypatch.setattr(
            notebook.subprocess,
            "Popen",
            lambda *args, **kwargs: _FakeChild(alive=False, returncode=2),
        )

        with pytest.raises(RuntimeError) as failure:
            _real_start_server("http://localhost", 8097, "/", 5)

        assert "status 2" in str(failure.value)
        assert log_path in str(failure.value)
        assert "It's Alive!" in str(failure.value)

    def test_a_server_that_never_answers_times_out(self, spawn, monkeypatch):
        _, log_path = spawn
        monkeypatch.setattr(notebook, "_server_is_up", lambda *args, **kwargs: False)

        with pytest.raises(RuntimeError) as failure:
            _real_start_server("http://localhost", 8097, "/", 0)

        assert "did not answer" in str(failure.value)
        assert log_path in str(failure.value)

    def test_a_missing_log_does_not_mask_the_failure(self, monkeypatch, tmp_path):
        assert notebook._log_tail(str(tmp_path / "absent.log")) == ""


class TestStopping:
    def test_a_live_server_is_asked_to_save_before_it_goes(self):
        # terminate() is SIGTERM, which the server unwinds through its atexit
        # save; killing it outright would drop whatever it had not written.
        child = _FakeChild()
        notebook._started[8097] = (child, "/tmp/log")

        notebook._stop_started_servers()

        assert child.terminated == 1
        assert child.killed == 0
        assert notebook._started == {}

    def test_a_server_that_ignores_the_signal_is_killed(self):
        class _Stubborn(_FakeChild):
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("visdom", timeout)

        child = _Stubborn()
        notebook._started[8097] = (child, "/tmp/log")

        notebook._stop_started_servers()

        assert child.killed == 1

    def test_a_server_that_already_exited_is_left_alone(self):
        child = _FakeChild(alive=False)
        notebook._started[8097] = (child, "/tmp/log")

        notebook._stop_started_servers()

        assert child.terminated == 0


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
