#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
from io import open
from setuptools import setup, find_packages

try:
    from importlib.metadata import version as get_metadata_version, PackageNotFoundError
except ImportError:
    try:
        from importlib_metadata import version as get_metadata_version, PackageNotFoundError
    except ImportError:
        raise ImportError(
            "importlib.metadata is not available. Install 'importlib_metadata' for Python < 3.8."
        )

try:
    import torch
    if (torch.__version__ < "0.3.1"):
        print(
            "[visdom] WARNING: Visdom support for pytorch less than version "
            "0.3.1 is unsupported. Visdom will still work for other purposes "
            "though."
        )
except Exception:
    pass  # User doesn't have torch


class Dist:
    """
    Minimal shim for pkg_resources.Distribution.

    Only the `.version` attribute is used in this codebase.
    Other attributes from pkg_resources.Distribution are not supported.
    """
    def __init__(self, version):
        self.version = version


def get_dist(pkgname):
    try:
        return Dist(get_metadata_version(pkgname))
    except PackageNotFoundError:
        return None

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'py/visdom/VERSION')) as version_file:
    version = version_file.read().strip()

readme = open('README.md', 'rt', encoding='utf8').read()

requirements = [
    'numpy>=1.8',
    'scipy',
    'requests',
    'tornado',
    'six',
    'jsonpatch',
    'websocket-client',
    'networkx'
]
pillow_req = 'pillow-simd' if get_dist('pillow-simd') is not None else 'pillow'
requirements.append(pillow_req)

setup(
    # Metadata
    name='visdom',
    version=version,
    author='Jack Urbanek, Allan Jabri, Laurens van der Maaten',
    author_email='jju@fb.com',
    url='https://github.com/facebookresearch/visdom',
    description='A tool for visualizing live, rich data for Torch and Numpy',
    long_description_content_type="text/markdown",
    long_description=readme,
    license='Apache-2.0',
    python_requires='>=3.8',

    # Package info
    packages=find_packages(where="py"),
    package_dir={'': 'py'},
    package_data={'visdom': ['static/*.*', 'static/**/*', 'py.typed', '*.pyi']},
    include_package_data=True,
    zip_safe=False,
    install_requires=requirements,
    entry_points={'console_scripts': ['visdom=visdom.server.run_server:download_scripts_and_run']}
)
