#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
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
    bb = "%sbootstrap@3.3.7/dist/" % b
    ext_files = {
        # - js
        "%sjquery@3.1.1/dist/jquery.min.js" % b: "jquery.min.js",
        "%sbootstrap@3.3.7/dist/js/bootstrap.min.js" % b: "bootstrap.min.js",
        "%sreact@16.2.0/umd/react.production.min.js" % b: "react-react.min.js",
        "%sreact-dom@16.2.0/umd/react-dom.production.min.js" % b: "react-dom.min.js",
        "%sreact-modal@3.1.10/dist/react-modal.min.js" % b: "react-modal.min.js",
        # here is another url in case the cdn breaks down again.
        # https://raw.githubusercontent.com/plotly/plotly.js/master/dist/plotly.min.js
        ## [shouldsee/visdom/package_version]:latest.min.js not pointing to latest.
        ## see https://github.com/plotly/plotly.py/issues/3651
        "https://cdn.plot.ly/plotly-2.11.1.min.js": "plotly-plotly.min.js",
        # Stanford Javascript Crypto Library for Password Hashing
        "%ssjcl@1.0.7/sjcl.js" % b: "sjcl.js",
        "%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js.map"
        % b: "layout-bin-packer.js.map",
        # d3 Libraries for plotting d3 graphs!
        "http://d3js.org/d3.v3.min.js": "d3.v3.min.js",
        "https://d3js.org/d3-selection-multi.v1.js": "d3-selection-multi.v1.js",
        # Library to download the svg to png
        "%ssave-svg-as-png@1.4.17/lib/saveSvgAsPng.js" % b: "saveSvgAsPng.js",
        # - css
        "%sreact-resizable@1.4.6/css/styles.css" % b: "react-resizable-styles.css",
        "%sreact-grid-layout@0.16.3/css/styles.css" % b: "react-grid-layout-styles.css",
        "%scss/bootstrap.min.css" % bb: "bootstrap.min.css",
        # - fonts
        "%sclassnames@2.2.5" % b: "classnames",
        "%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js"
        % b: "layout_bin_packer.js",
        "%sfonts/glyphicons-halflings-regular.eot"
        % bb: "glyphicons-halflings-regular.eot",
        "%sfonts/glyphicons-halflings-regular.woff2"
        % bb: "glyphicons-halflings-regular.woff2",
        "%sfonts/glyphicons-halflings-regular.woff"
        % bb: "glyphicons-halflings-regular.woff",
        "%sfonts/glyphicons-halflings-regular.ttf"
        % bb: "glyphicons-halflings-regular.ttf",
        "%sfonts/glyphicons-halflings-regular.svg#glyphicons_halflingsregular"
        % bb: "glyphicons-halflings-regular.svg#glyphicons_halflingsregular",  # noqa
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
    is_built = visdom.__version__ == "no_version_file"
    if os.path.exists(built_path):
        with open(built_path, "r") as build_file:
            build_version = build_file.read().strip()
        if build_version == visdom.__version__:
            is_built = True
        else:
            os.remove(built_path)
    if not is_built:
        print("Downloading scripts, this may take a little while")

    # download files one-by-one:
    for (key, val) in ext_files.items():

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

    cdnjs_url = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/"
    mathjax_dir = os.path.join(*cdnjs_url.split("/")[-3:])
    mathjax_path = [
        "config/Safe.js?V=2.7.5",
        "config/TeX-AMS-MML_HTMLorMML.js?V=2.7.5",
        "extensions/Safe.js?V=2.7.5",
        "jax/output/SVG/fonts/TeX/fontdata.js?V=2.7.5",
        "jax/output/SVG/jax.js?V=2.7.5",
        "jax/output/SVG/fonts/TeX/Size1/Regular/Main.js?V=2.7.5",
        "jax/output/SVG/config.js?V=2.7.5",
        "MathJax.js?config=TeX-AMS-MML_HTMLorMML%2CSafe.js&#038;ver=4.1",
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
            build_file.write(visdom.__version__)
