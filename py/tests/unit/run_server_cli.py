#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The command line that starts the server, and the asset fetch behind it.

``run_server.main`` is the only place several policies live: what counts as a
port, how ``-base_url`` is normalised, and how credentials are taken from the
environment instead of a prompt. It ends in a blocking ``start_server``, so
every test here patches that out and asserts on the arguments it was handed.

``build.download_scripts`` is exercised with a fake opener. The point is the URL
table, the subdirectory routing and the ``version.built`` cache stamp -- never
the network, so both the urllib opener and ``requests.get`` are replaced.
"""

import argparse
import logging
import os
from urllib.error import HTTPError, URLError

import pytest

import visdom
from visdom.server import build, run_server
from visdom.server.run_server import MAX_PORT, PortValidationError, valid_port

pytestmark = pytest.mark.unit


# -- Port validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", 1),
        ("8097", 8097),
        (str(MAX_PORT), MAX_PORT),
        (8097, 8097),
        (MAX_PORT, MAX_PORT),
        (" 8097 ", 8097),
    ],
)
def test_a_port_in_range_is_returned_as_an_int(value, expected):
    assert valid_port(value) == expected


@pytest.mark.parametrize("value", [0, -1, MAX_PORT + 1, "0", "-1", "70000"])
def test_a_port_outside_the_range_is_rejected(value):
    """Port 0 is excluded on purpose -- browsers refuse it with ERR_UNSAFE_PORT."""
    with pytest.raises(PortValidationError) as excinfo:
        valid_port(value)
    assert "between 1 and {0}".format(MAX_PORT) in str(excinfo.value)


@pytest.mark.parametrize("value", ["abc", "", None, [], "8097.0"])
def test_a_port_that_is_not_a_whole_number_is_rejected(value):
    with pytest.raises(PortValidationError) as excinfo:
        valid_port(value)
    assert "must be an integer" in str(excinfo.value)


@pytest.mark.parametrize("value", [True, False, 8097.0, 1.5])
def test_bools_and_floats_are_rejected_before_int_coercion(value):
    """``int(True)`` is 1 and ``int(8097.0)`` is 8097; neither is a port a user meant."""
    with pytest.raises(PortValidationError):
        valid_port(value)


def test_the_error_is_both_a_value_error_and_an_argparse_error():
    """argparse keeps the custom message; programmatic callers still see ValueError."""
    error = PortValidationError("boom")
    assert isinstance(error, ValueError)
    assert isinstance(error, argparse.ArgumentTypeError)


# -- main(): argument handling -------------------------------------------------


@pytest.fixture
def started(monkeypatch, tmp_path):
    """Run ``main()`` with a given argv and capture ``start_server``'s kwargs."""
    captured = {}

    def fake_start_server(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(run_server, "start_server", fake_start_server)

    def run(*argv):
        args = ["visdom", "-env_path", str(tmp_path)] + list(argv)
        monkeypatch.setattr("sys.argv", args)
        run_server.main()
        return captured

    return run


@pytest.fixture(autouse=True)
def restore_root_log_level():
    """``main()`` sets the root level globally; put it back for the next test."""
    previous = logging.getLogger().level
    yield
    logging.getLogger().setLevel(previous)


def test_the_default_base_url_becomes_an_empty_prefix(started):
    """Routes append their own leading slash, so the default must not add one."""
    assert started()["base_url"] == ""


def test_an_explicit_base_url_is_passed_through(started):
    assert started("-base_url", "/visdom")["base_url"] == "/visdom"


def test_a_base_url_without_a_leading_slash_is_refused(started):
    with pytest.raises(AssertionError):
        started("-base_url", "visdom")


def test_a_base_url_with_a_trailing_slash_is_refused(started):
    with pytest.raises(AssertionError):
        started("-base_url", "/visdom/")


def test_the_port_reaches_the_server_as_an_int(started):
    assert started("-port", "8123")["port"] == 8123


def test_an_invalid_port_stops_the_command(started):
    with pytest.raises(SystemExit) as excinfo:
        started("-port", "0")
    assert excinfo.value.code == 2


def test_the_switch_flags_default_to_off(started):
    kwargs = started()
    assert kwargs["readonly"] is False
    assert kwargs["bind_local"] is False
    assert kwargs["eager_data_loading"] is False
    assert kwargs["use_frontend_client_polling"] is False
    assert kwargs["user_credential"] is None


def test_the_switch_flags_are_forwarded(started):
    kwargs = started(
        "-readonly",
        "-bind_local",
        "-eager_data_loading",
        "-use_frontend_client_polling",
    )
    assert kwargs["readonly"] is True
    assert kwargs["bind_local"] is True
    assert kwargs["eager_data_loading"] is True
    assert kwargs["use_frontend_client_polling"] is True


def test_the_ssl_pair_is_forwarded(started):
    kwargs = started("-ssl_certfile", "cert.pem", "-ssl_keyfile", "key.pem")
    assert (kwargs["ssl_certfile"], kwargs["ssl_keyfile"]) == ("cert.pem", "key.pem")


@pytest.mark.parametrize("flag", ["-ssl_certfile", "-ssl_keyfile"])
def test_half_an_ssl_pair_stops_the_command(started, flag):
    with pytest.raises(SystemExit) as excinfo:
        started(flag, "only.pem")
    assert excinfo.value.code == 2


@pytest.mark.parametrize("value,expected", [("DEBUG", 10), ("20", 20), ("WARNING", 30)])
def test_the_logging_level_accepts_a_name_or_a_number(started, value, expected):
    started("-logging_level", value)
    assert logging.getLogger().level == expected


def test_an_unknown_logging_level_is_reported(started):
    with pytest.raises(KeyError):
        started("-logging_level", "CHATTY")


# -- main(): credentials from the environment ---------------------------------


@pytest.fixture
def env_login(monkeypatch, started):
    """``-enable_login`` reading credentials from the environment, cookie stubbed."""
    cookies = []
    monkeypatch.setattr(run_server, "set_cookie", lambda value: cookies.append(value))
    monkeypatch.setenv("VISDOM_USE_ENV_CREDENTIALS", "1")

    def run(*argv):
        return started("-enable_login", "-force_new_cookie", *argv), cookies

    return run


def test_env_credentials_are_hashed_before_they_are_stored(env_login, monkeypatch):
    """The password is never handed to the Application in the clear."""
    monkeypatch.setenv("VISDOM_USERNAME", "admin")
    monkeypatch.setenv("VISDOM_PASSWORD", "hunter2")
    monkeypatch.setenv("VISDOM_COOKIE", "cookie-value")
    kwargs, _ = env_login()
    credential = kwargs["user_credential"]
    assert credential["username"] == "admin"
    assert "hunter2" not in credential["password"]


def test_the_cookie_is_taken_from_the_environment_too(env_login, monkeypatch):
    monkeypatch.setenv("VISDOM_USERNAME", "admin")
    monkeypatch.setenv("VISDOM_PASSWORD", "hunter2")
    monkeypatch.setenv("VISDOM_COOKIE", "cookie-value")
    _, cookies = env_login()
    assert cookies == ["cookie-value"]


@pytest.mark.parametrize("missing", ["VISDOM_USERNAME", "VISDOM_PASSWORD"])
def test_half_a_credential_pair_stops_the_command(env_login, monkeypatch, missing):
    monkeypatch.setenv("VISDOM_USERNAME", "admin")
    monkeypatch.setenv("VISDOM_PASSWORD", "hunter2")
    monkeypatch.setenv("VISDOM_COOKIE", "cookie-value")
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit) as excinfo:
        env_login()
    assert excinfo.value.code == 1


def test_a_missing_cookie_variable_stops_the_command(env_login, monkeypatch):
    """Without a cookie there is nothing to sign sessions with, so it is fatal."""
    monkeypatch.setenv("VISDOM_USERNAME", "admin")
    monkeypatch.setenv("VISDOM_PASSWORD", "hunter2")
    monkeypatch.delenv("VISDOM_COOKIE", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        env_login()
    assert excinfo.value.code == 1


# -- start_server(): SSL material ---------------------------------------------


def test_a_missing_certificate_is_reported_before_the_port_is_bound(tmp_path):
    keyfile = tmp_path / "key.pem"
    keyfile.write_text("key")
    with pytest.raises(FileNotFoundError) as excinfo:
        run_server.start_server(
            env_path=str(tmp_path),
            ssl_certfile=str(tmp_path / "absent.pem"),
            ssl_keyfile=str(keyfile),
        )
    assert "certificate" in str(excinfo.value)


def test_a_missing_key_is_reported_too(tmp_path):
    certfile = tmp_path / "cert.pem"
    certfile.write_text("cert")
    with pytest.raises(FileNotFoundError) as excinfo:
        run_server.start_server(
            env_path=str(tmp_path),
            ssl_certfile=str(certfile),
            ssl_keyfile=str(tmp_path / "absent.pem"),
        )
    assert "key" in str(excinfo.value)


# -- build.download_scripts() --------------------------------------------------


class FakeOpener:
    """Stands in for the urllib opener, recording what would have been fetched."""

    def __init__(self, failures=None):
        self.requested = []
        self.failures = failures or {}

    def open(self, req):
        url = req.get_full_url()
        self.requested.append(url)
        if url in self.failures:
            raise self.failures[url]
        return _FakeResponse(b"asset-bytes")


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body


class _MathjaxResponse:
    """What ``requests.get`` returns for the MathJax bundle."""

    def __init__(self, log, url):
        log.append(url)
        self.content = b"mathjax"


@pytest.fixture
def offline_downloads(monkeypatch):
    """Replace both fetch paths -- urllib for assets, requests for MathJax."""
    monkeypatch.setattr(visdom, "__version__", "9.9.9")
    mathjax = []
    handlers = []

    def install(opener):
        def fake_build_opener(handler):
            handlers.append(handler)
            return opener

        monkeypatch.setattr(build.request, "build_opener", fake_build_opener)
        monkeypatch.setattr(build.request, "install_opener", lambda _opener: None)
        monkeypatch.setattr("requests.get", lambda url: _MathjaxResponse(mathjax, url))
        return handlers

    install.mathjax = mathjax
    return install


def _run_download(offline_downloads, install_dir, failures=None):
    opener = FakeOpener(failures=failures)
    handlers = offline_downloads(opener)
    build.download_scripts(install_dir=str(install_dir))
    return opener, handlers


def test_every_asset_is_fetched_over_https_from_a_known_host(
    offline_downloads, tmp_path
):
    opener, _ = _run_download(offline_downloads, tmp_path)
    hosts = {url.split("/")[2] for url in opener.requested}
    assert all(url.startswith("https://") for url in opener.requested)
    assert hosts == {"unpkg.com", "cdn.plot.ly", "d3js.org"}


def test_assets_are_filed_by_extension(offline_downloads, tmp_path):
    """Each asset lands in the directory its extension implies.

    Nothing in the current list is extensionless, so the ``fonts/`` fallback in
    ``build.download_scripts`` is unreachable and is not asserted here.
    """
    _run_download(offline_downloads, tmp_path)
    static = tmp_path / "static"
    assert (static / "js" / "plotly-plotly.min.js").exists()
    assert (static / "js" / "layout-bin-packer.js.map").exists()
    assert (static / "css" / "react-resizable-styles.css").exists()


def test_the_mathjax_bundle_is_fetched_into_its_versioned_path(
    offline_downloads, tmp_path
):
    _run_download(offline_downloads, tmp_path)
    bundle = tmp_path / "static" / "js" / "mathjax" / "3.2.2" / "es5" / "tex-mml-svg.js"
    assert bundle.exists()
    assert offline_downloads.mathjax


def test_the_build_stamp_records_the_installed_version(offline_downloads, tmp_path):
    """The stamp is the version plus a fingerprint of the asset list.

    Editing the list of files to fetch changes the fingerprint, so a checkout
    that gained an asset refetches instead of trusting the version alone.
    """
    _run_download(offline_downloads, tmp_path)
    stamp = (tmp_path / "static" / "version.built").read_text().strip()
    version, _, assets_hash = stamp.partition(":")

    assert version == "9.9.9"
    assert len(assets_hash) == 64


def test_a_second_run_downloads_nothing(offline_downloads, tmp_path):
    """The stamp plus the files on disk is what keeps `visdom` startup offline."""
    _run_download(offline_downloads, tmp_path)
    opener, _ = _run_download(offline_downloads, tmp_path)
    assert opener.requested == []


def test_a_stale_stamp_forces_a_refetch(offline_downloads, tmp_path):
    _run_download(offline_downloads, tmp_path)
    (tmp_path / "static" / "version.built").write_text("0.0.1")
    opener, _ = _run_download(offline_downloads, tmp_path)
    assert opener.requested
    assert (
        (tmp_path / "static" / "version.built").read_text().strip().startswith("9.9.9:")
    )


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://d3js.org/d3-selection-multi.v1.js", 404, "nf", {}, None),
        URLError("offline"),
    ],
)
def test_a_failed_download_is_logged_and_the_rest_continue(
    offline_downloads, tmp_path, error
):
    """A CDN outage must not abort the install half way through."""
    url = "https://d3js.org/d3-selection-multi.v1.js"
    opener, _ = _run_download(offline_downloads, tmp_path, failures={url: error})
    assert len(opener.requested) > 1
    assert not (tmp_path / "static" / "js" / "d3-selection-multi.v1.js").exists()
    assert (tmp_path / "static" / "js" / "d3.v3.min.js").exists()


def test_proxies_are_passed_to_the_opener(offline_downloads, tmp_path):
    handlers = offline_downloads(FakeOpener())
    build.download_scripts(
        proxies={"http": "http://proxy:3128"}, install_dir=str(tmp_path)
    )
    assert isinstance(handlers[0], build.request.ProxyHandler)


def test_the_static_tree_is_created_when_it_is_missing(offline_downloads, tmp_path):
    target = tmp_path / "fresh" / "install"
    _run_download(offline_downloads, target)
    for sub in ("js", "css", "fonts"):
        assert os.path.isdir(target / "static" / sub)
