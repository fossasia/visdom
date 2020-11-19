#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
from io import open
from setuptools import setup
from pkg_resources import get_distribution, DistributionNotFound


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


def get_dist(pkgname):
    try:
        return get_distribution(pkgname)
    except DistributionNotFound:
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
    'pyzmq',
    'six',
    'jsonpatch',
    'websocket-client',
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
    long_description=readme,
    license='Apache-2.0',

    # Package info
    packages=['visdom'],
    package_dir={'': 'py'},
    package_data={'visdom': ['static/*.*', 'static/**/*', 'py.typed', '*.pyi']},
    include_package_data=True,
    zip_safe=False,
    install_requires=requirements,
    entry_points={'console_scripts': ['visdom=visdom.server:download_scripts_and_run']}
)
