from setuptools import setup
from setuptools.command.install import install
from setuptools.command.develop import develop

import six.moves.urllib.request as request
from six import iteritems

from pathlib import Path
import shutil

readme = open('README.md').read()

requirements = [
    'numpy',
    'pillow',
    'requests',
    'tornado',
    'pyzmq',
    'six',
    'pathlib'
]

def download_scripts(path):
    path = Path(path)

    ext_files = { 'https://unpkg.com/bootstrap@3.3.7/dist/css/bootstrap.min.css' : 'bootstrap.min.css',
                'https://unpkg.com/jquery@3.1.1/dist/jquery.min.js' : 'jquery.min.js',
                'https://unpkg.com/bootstrap@3.3.7/dist/js/bootstrap.min.js' : 'bootstrap.min.js',
                'https://unpkg.com/react-resizable@1.4.6/css/styles.css' : 'react-resizable-styles.css',
                'https://unpkg.com/react-grid-layout@0.14.0/css/styles.css': 'react-grid-layout-styles.css',
                'https://unpkg.com/react@15/dist/react.min.js' : 'react-react.min.js',
                'https://unpkg.com/react-dom@15/dist/react-dom.min.js' : 'react-dom.min.js',
                'https://unpkg.com/classnames@2.2.5' : 'classnames',
                'https://unpkg.com/layout-bin-packer@1.2.2' : 'layout_bin_packer',
                'https://cdn.rawgit.com/STRML/react-grid-layout/0.14.0/dist/react-grid-layout.min.js' : 'react-grid-layout.min.js',
                'https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-AMS-MML_SVG': 'mathjax-MathJax.js',
                'https://cdn.rawgit.com/plotly/plotly.js/master/dist/plotly.min.js': 'plotly-plotly.min.js'}

    for k,v in iteritems(ext_files):
        req = request.Request( k, headers={'User-Agent': 'Chrome/30.0.0.0'})
        data = request.urlopen(req).read()
        sub_dir = 'js' if 'js' in k else 'css'
        with open( str(path / 'visdom' / 'static' / sub_dir / v), 'wb') as data_file:
            data_file.write(data)


class pose_develop(develop):
    def run(self):
        develop.run(self)
        download_scripts(self.install_lib)

class post_install(install):
    def run(self):
        install.run(self)
        download_scripts(self.install_lib)


setup(
    # Metadata
    name='visdom',
    version='0.1.04',
    author='Allan Jabri',
    author_email='ajabri@fb.com',
    url='https://github.com/facebookresearch/visdom',
    description='A tool for visualizing live, rich data for Torch and Numpy',
    long_description=readme,
    license='CC-BY-4.0',

    # Package info
    packages=['visdom'],
    package_dir={'visdom': 'py'},
    package_data={'visdom': ['static/*.*', 'static/**/*']},
    include_package_data=True,
    zip_safe=True,
    install_requires=requirements,

    # Post install hooks
    cmdclass={'install': post_install, 'develop':pose_develop}
)
