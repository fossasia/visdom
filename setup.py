from distutils.core import setup

setup(
    name='visdom',
    version='0.1dev',
    packages=['visdom'],
    package_dir={'visdom': 'py'},
    requires=['numpy', 'PIL', 'tornado', 'zmq'],
)
