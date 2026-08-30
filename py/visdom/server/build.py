#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import hashlib
import os
import visdom
from urllib import request
from urllib.error import HTTPError, URLError
from visdom.utils.shared_utils import get_visdom_path


def download_scripts(proxies=None, install_dir=None):
    """
    Function to download all of the javascript, css, and font dependencies,
    and put them in the correct locations to run the server
    """
    print("Checking for scripts.")

    # location in which to download stuff:
    if install_dir is None:
        install_dir = get_visdom_path()

    # all files that need to be downloaded:
    b = "https://unpkg.com/"
    ext_files = {
        # - js
        # here is another url in case the cdn breaks down again.
        # https://raw.githubusercontent.com/plotly/plotly.js/master/dist/plotly.min.js
        ## [shouldsee/visdom/package_version]:latest.min.js not pointing to latest.
        ## see https://github.com/plotly/plotly.py/issues/3651
        "https://cdn.plot.ly/plotly-3.7.0.min.js": "plotly-plotly.min.js",
        # Stanford Javascript Crypto Library for Password Hashing
        "%ssjcl@1.0.7/sjcl.js" % b: "sjcl.js",
        "%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js.map"
        % b: "layout-bin-packer.js.map",
        # d3 Libraries for plotting d3 graphs!
        "https://d3js.org/d3.v3.min.js": "d3.v3.min.js",
        "https://d3js.org/d3-selection-multi.v1.js": "d3-selection-multi.v1.js",
        # Library to download the svg to png
        "%ssave-svg-as-png@1.4.17/lib/saveSvgAsPng.js" % b: "saveSvgAsPng.js",
        # - css
        "%sreact-resizable@3.1.3/css/styles.css" % b: "react-resizable-styles.css",
        "%sreact-grid-layout@2.2.3/css/styles.css" % b: "react-grid-layout-styles.css",
        # .js extension routes this to js/, not css/
        "%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js"
        % b: "layout_bin_packer.js",
    }

    # make sure all relevant folders exist:
    dir_list = [
        "%s" % install_dir,
        "%s/static" % install_dir,
        "%s/static/js" % install_dir,
        "%s/static/css" % install_dir,
        "%s/static/fonts" % install_dir,
    ]
    for directory in dir_list:
        if not os.path.exists(directory):
            os.makedirs(directory)

    # set up proxy handler:
    handler = (
        request.ProxyHandler(proxies) if proxies is not None else request.BaseHandler()
    )
    opener = request.build_opener(handler)
    request.install_opener(opener)

    built_path = os.path.join(install_dir, "static/version.built")
    assets_hash = hashlib.sha256(
        repr(sorted(ext_files.items())).encode("utf-8")
    ).hexdigest()
    build_marker = "{0}:{1}".format(visdom.__version__, assets_hash)
    is_built = visdom.__version__ == "no_version_file"
    if os.path.exists(built_path):
        with open(built_path, "r") as build_file:
            build_version = build_file.read().strip()
        if build_version == build_marker:
            is_built = True
        else:
            os.remove(built_path)
    if not is_built:
        print("Downloading scripts, this may take a little while")

    # download files one-by-one:
    for key, val in ext_files.items():
        # set subdirectory:
        if val.endswith(".js") or val.endswith(".js.map"):
            sub_dir = "js"
        elif val.endswith(".css"):
            sub_dir = "css"
        else:
            sub_dir = "fonts"

        # download file:
        filename = "%s/static/%s/%s" % (install_dir, sub_dir, val)
        if not os.path.exists(filename) or not is_built:
            req = request.Request(key, headers={"User-Agent": "Chrome/30.0.0.0"})
            try:
                data = opener.open(req).read()
                with open(filename, "wb") as fwrite:
                    fwrite.write(data)
            except HTTPError as exc:
                logging.error("Error {} while downloading {}".format(exc.code, key))
            except URLError as exc:
                logging.error("Error {} while downloading {}".format(exc.reason, key))

    # Download MathJax Js Files
    import requests

    mathjax_version = "3.2.2"
    cdnjs_url = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/%s/" % mathjax_version
    mathjax_dir = os.path.join(*cdnjs_url.split("/")[-3:])
    mathjax_path = [
        "es5/tex-mml-svg.js",
    ]
    mathjax_dir_path = "%s/static/%s/%s" % (install_dir, "js", mathjax_dir)

    for path in mathjax_path:
        filename = path.split("/")[-1].split("?")[0]
        extracted_directory = os.path.join(mathjax_dir_path, *path.split("/")[:-1])
        if not os.path.exists(extracted_directory):
            os.makedirs(extracted_directory)
        if not os.path.exists(os.path.join(extracted_directory, filename)):
            js_file = requests.get(cdnjs_url + path)
            with open(os.path.join(extracted_directory, filename), "wb+") as file:
                file.write(js_file.content)

    if not is_built:
        with open(built_path, "w+") as build_file:
            build_file.write(build_marker)
