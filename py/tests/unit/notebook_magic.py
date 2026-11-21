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
import shlex
import subprocess
import sys
import textwrap

import pytest
import requests

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
    """Records how the magic built its client, and what it asked show() for.

    ``server_is_up`` is what the real constructor's registration POST does or
    does not reach, and so what the client's own ``_env_registered`` ends up
    saying.
    """

    built = []
    server_is_up = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.registrations = []
        self._env_registered = _FakeVisdom.server_is_up
        _FakeVisdom.built.append(self)

    def _register_env(self, env):
        self.registrations.append(env)
        self._env_registered = _FakeVisdom.server_is_up
        return self._env_registered

    def show(self, height=600, width="100%"):
        return _FakeEmbed(self, height, width)


# Captured before the autouse fixture puts the fake in its place: the tests
# that are about Visdom itself need the class the magic really builds.
_REAL_CLIENT = notebook._NotebookClient


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No real client, and no state carried between tests."""
    notebook._clients.clear()
    _FakeVisdom.built = []
    _FakeVisdom.server_is_up = True
    monkeypatch.setattr(notebook, "_NotebookClient", _FakeVisdom)
    yield
    notebook._clients.clear()


def _parse(line=""):
    return notebook._build_parser().parse_args(line.split())


class TestParsing:
    def test_the_defaults_are_a_local_server_and_the_main_env(self):
        args = _parse()

        # --port has no default of its own: the port can be part of --server
        # instead, and "the line did not say" is what tells that apart from
        # the two of them disagreeing. _resolve_port fills in 8097.
        assert (args.server, args.port) == ("http://localhost", None)
        assert (args.env, args.height, args.width) == ("main", 600, "100%")
        assert notebook._resolve_port(None, None) == 8097

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

    def test_a_decimal_dimension_is_pixels_too(self):
        # Read as CSS instead -- which is what a whole-number-only test makes
        # of it -- this reaches the browser as 'height:600.5', a length with
        # no unit, and the browser drops the declaration: the flag is then
        # ignored rather than refused.
        args = _parse("--height 600.5")

        assert args.height == 600.5
        assert visdom._embed_size(args.height) == "600.5px"

    def test_a_decimal_dimension_is_a_length_the_browser_keeps(self):
        # Through the embed itself, which is what the cell displays.
        embed = visdom._NotebookEmbed(
            "http://localhost:8097/env/main", _parse("--height 600.5").height, "100%"
        )

        assert embed.height == "600.5px"
        assert "height:600.5px" in embed._repr_html_()

    @pytest.mark.parametrize(
        "line", ["--height 0", "--height -1", "--height=-400", "--height -600.5"]
    )
    def test_a_nonpositive_dimension_is_a_usage_error(self, line):
        # A signed number is a number: '-1' used to pass the digit test, go
        # through as a CSS length and reach the browser as 'height:-1'.
        with pytest.raises(ValueError):
            _parse(line)

    @pytest.mark.parametrize("line", ["--height ''", "--width ';display:none'"])
    def test_a_dimension_the_embed_would_refuse_is_refused_here(self, line):
        # show() is what rejects these, and the env is registered between the
        # parse and the embed -- so a dimension checked only there would have
        # created an env on the server on its way to the error.
        with pytest.raises(ValueError, match="CSS length"):
            notebook._build_parser().parse_args(shlex.split(line))

        assert _FakeVisdom.built == []

    @pytest.mark.parametrize(
        "line,wanted",
        [
            ("--port 99999", "between 1 and 65535"),
            ("--port eight", "port must be a number"),
            ("--height 0", "must be positive"),
            ("--height -1", "must be positive"),
            ("--height ''", "must be a CSS length"),
            ("--height nan", "must be finite"),
            ("--height inf", "must be finite"),
        ],
    )
    def test_a_bad_value_is_explained_rather_than_named(self, line, wanted):
        # argparse keeps an ArgumentTypeError's message but replaces a
        # ValueError's with "invalid _port value: ...", which leaks the
        # converter's own name and loses the explanation.
        with pytest.raises(ValueError, match=wanted):
            notebook._build_parser().parse_args(shlex.split(line))

    def test_an_unknown_flag_does_not_end_the_kernel(self):
        # argparse would answer this with SystemExit, which in a notebook reads
        # as a crashed kernel rather than a typo.
        with pytest.raises(ValueError, match="--logdir"):
            _parse("--logdir runs")

    def test_help_is_printed_rather_than_raised(self, capsys):
        # Printed, not returned: a cell displays a returned string through its
        # repr, which shows the usage in quotes with literal '\n' escapes
        # where the line breaks should be.
        assert notebook.visdom_magic("--help") is None

        printed = capsys.readouterr().out
        assert "%visdom" in printed
        assert "--env" in printed
        assert "\\n" not in printed
        assert printed.count("\n") > 1
        assert _FakeVisdom.built == []


class TestServerUrl:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("http://localhost", ("http://localhost", None)),
            ("localhost", ("http://localhost", None)),
            ("gpu-box.example.com", ("http://gpu-box.example.com", None)),
            ("https://visdom.example.com", ("https://visdom.example.com", None)),
            ("http://localhost/", ("http://localhost", None)),
            ("  http://localhost  ", ("http://localhost", None)),
            ("localhost:8097", ("http://localhost", 8097)),
            ("http://localhost:9000", ("http://localhost", 9000)),
            ("https://gpu-box.example.com:9000", ("https://gpu-box.example.com", 9000)),
            ("http://user:secret@gpu-box:9000", ("http://user:secret@gpu-box", 9000)),
            ("http://[::1]:9000", ("http://[::1]", 9000)),
            ("http://[::1]", ("http://[::1]", None)),
            ("localhost:", ("http://localhost", None)),
        ],
    )
    def test_the_port_comes_out_of_the_url_the_client_keeps(self, given, expected):
        # The client builds every request as 'server:port/...', so a port left
        # in the url is a second port: 'localhost:8097' on the default port
        # asked for 'http://localhost:8097:8097/env/main'.
        assert notebook._normalize_server(given) == expected

    @pytest.mark.parametrize(
        "given", ["htps://gpu-box.example.com", "ftp://gpu-box.example.com", "://box"]
    )
    def test_a_scheme_that_is_not_http_is_refused(self, given):
        # The http fallback is for a bare host only. Re-parsing these as one
        # reads 'htps://box' as the host 'htps:' and drops the rest, so the
        # client was handed an address nothing could ever answer at.
        with pytest.raises(ValueError, match="http or https"):
            notebook._normalize_server(given)

    def test_a_scheme_typo_never_reaches_the_client(self):
        with pytest.raises(ValueError, match="http or https"):
            notebook.visdom_magic("--server htps://gpu-box.example.com")

        assert _FakeVisdom.built == []

    @pytest.mark.parametrize(
        "given",
        [
            "http://localhost/visdom",
            "localhost:8097/visdom",
            "http://localhost/?env=main",
            "http://localhost/#main",
        ],
    )
    def test_anything_after_the_host_is_refused_rather_than_dropped(self, given):
        # A dashboard mounted under a proxy path is a different address, not
        # this one with a decoration: dropping the path embeds the server root
        # instead, which is whatever else is answering there.
        with pytest.raises(ValueError, match="nothing"):
            notebook._normalize_server(given)

    @pytest.mark.parametrize("given", ["localhost:http", "localhost:99999"])
    def test_a_port_in_the_url_that_is_not_a_port_is_refused(self, given):
        with pytest.raises(ValueError, match="usable port"):
            notebook._normalize_server(given)

    def test_port_zero_in_the_url_is_refused_as_it_is_in_the_flag(self):
        with pytest.raises(ValueError, match="between 1 and 65535"):
            notebook._normalize_server("box:0")

    @pytest.mark.parametrize("given", ["http://", "http://:8097"])
    def test_a_url_that_names_no_host_is_refused(self, given):
        with pytest.raises(ValueError, match="no host"):
            notebook._normalize_server(given)


class TestPort:
    def test_the_url_names_it(self):
        assert notebook._resolve_port(9000, None) == 9000

    def test_the_flag_names_it(self):
        assert notebook._resolve_port(None, 9000) == 9000

    def test_neither_names_it(self):
        assert notebook._resolve_port(None, None) == 8097

    def test_both_name_the_same_one(self):
        assert notebook._resolve_port(9000, 9000) == 9000

    def test_two_different_ports_is_a_usage_error(self):
        # Rather than picking one, which is how '--port 9000' ends up
        # silently ignored.
        with pytest.raises(ValueError, match="give the port once"):
            notebook._resolve_port(8097, 9000)


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

    def test_a_bare_line_is_localhost_8097_and_main(self):
        notebook.visdom_magic("")

        kwargs = _FakeVisdom.built[0].kwargs
        assert (kwargs["server"], kwargs["port"], kwargs["env"]) == (
            "http://localhost",
            8097,
            "main",
        )

    def test_a_port_in_the_server_url_is_the_port_the_client_is_given(self):
        # And it is not left in the url as well: the client builds every
        # request as 'server:port/...', so this used to ask for
        # 'http://localhost:9000:8097/env/main'.
        notebook.visdom_magic("--server localhost:9000")

        kwargs = _FakeVisdom.built[0].kwargs
        assert (kwargs["server"], kwargs["port"]) == ("http://localhost", 9000)

    def test_the_same_port_in_both_places_is_not_a_disagreement(self):
        notebook.visdom_magic("--server localhost:9000 --port 9000")

        assert _FakeVisdom.built[0].kwargs["port"] == 9000

    def test_two_different_ports_never_reach_the_client(self):
        with pytest.raises(ValueError, match="give the port once"):
            notebook.visdom_magic("--server localhost:9000 --port 8097")

        assert _FakeVisdom.built == []

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

    def test_a_registration_that_never_landed_is_tried_again(self):
        # A %visdom run before the server was up builds a client whose env was
        # never created, and the frame shows the dashboard's 404 for it.
        # Caching that client as it is makes the 404 permanent -- and
        # re-running the cell, the one thing anybody would try, changes
        # nothing.
        _FakeVisdom.server_is_up = False
        notebook.visdom_magic("--env run-7")

        _FakeVisdom.server_is_up = True
        again = notebook.visdom_magic("--env run-7")

        # Still the one client, because the thread it holds is there either
        # way, but the environment it names now exists.
        assert len(_FakeVisdom.built) == 1
        assert again.client.registrations == ["run-7"]
        assert again.client._env_registered is True

    def test_a_client_that_did_register_is_not_asked_again(self):
        notebook.visdom_magic("--env run-7")
        again = notebook.visdom_magic("--env run-7")

        assert again.client.registrations == []

    def test_a_different_env_gets_its_own_client(self):
        # The registration is per-env, and it happens in the constructor.
        notebook.visdom_magic("--env run-7")
        notebook.visdom_magic("--env run-8")

        assert [built.kwargs["env"] for built in _FakeVisdom.built] == [
            "run-7",
            "run-8",
        ]


class TestTheRealClient:
    """What the magic relies on ``Visdom`` doing, with only its POST replaced."""

    def _build(self):
        return _REAL_CLIENT(
            server="http://localhost",
            port=8097,
            env="run-7",
            use_incoming_socket=False,
        )

    def test_a_registration_that_landed_is_recorded_as_such(self, monkeypatch):
        monkeypatch.setattr(
            visdom.Visdom, "_handle_post", lambda self, url, data=None: ""
        )

        assert self._build()._env_registered is True

    def test_a_registration_that_did_not_land_is_recorded_as_such(self, monkeypatch):
        # Which is the whole of what the magic has to go on: the constructor
        # warns and hands back a client either way.
        def refuse(self, url, data=None):
            raise requests.ConnectionError("nothing is listening there")

        monkeypatch.setattr(visdom.Visdom, "_handle_post", refuse)

        assert self._build()._env_registered is False

    def test_registering_again_is_the_same_post(self, monkeypatch):
        posted = []

        def record(self, url, data=None):
            posted.append(url)
            return ""

        monkeypatch.setattr(visdom.Visdom, "_handle_post", record)
        client = self._build()

        client._register_env("run-7")

        assert posted == ["http://localhost:8097/env/run-7"] * 2

    def test_the_registration_post_cannot_hold_the_cell_open(self, monkeypatch):
        timeouts = []

        class _Reply:
            status_code = 200
            text = ""

        class _Session:
            def post(self, url, data=None, timeout=None):
                timeouts.append(timeout)
                return _Reply()

        monkeypatch.setattr(visdom.Visdom, "session", property(lambda self: _Session()))

        self._build()

        # The client leaves the read half of a POST unbounded on purpose: a
        # send can carry a video the server is still writing out. A cell has
        # nothing to interrupt it, so the magic's client does not.
        assert visdom.Visdom.post_timeout == (20, None)
        assert timeouts == [(20, 20)]


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

    def test_unload_leaves_a_magic_something_else_registered(self):
        # Unloading this extension is not a licence to remove the %visdom
        # someone else put there after it loaded.
        shell = _FakeShell()
        notebook.load_ipython_extension(shell)

        def replacement(line=""):
            return None

        shell.register_magic_function(replacement, "line", "visdom")
        notebook.unload_ipython_extension(shell)

        assert shell.magics_manager.magics["line"]["visdom"] is replacement


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
