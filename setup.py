from setuptools import setup

readme = open('README.md').read()

requirements = [
    'numpy>=1.8',
    'scipy',
    'pillow',
    'requests',
    'tornado',
    'pyzmq',
    'six',
    'torchfile',
    'websocket-client',
]

setup(
    # Metadata
    name='visdom',
    version='0.1.7.2',
    author='Allan Jabri, Jack Urbanek, Laurens van der Maaten',
    author_email='jju@fb.com',
    url='https://github.com/facebookresearch/visdom',
    description='A tool for visualizing live, rich data for Torch and Numpy',
    long_description=readme,
    license='CC-BY-4.0',

    # Package info
    packages=['visdom'],
    package_dir={'visdom': 'py'},
    package_data={'visdom': ['static/*.*', 'static/**/*']},
    include_package_data=True,
    zip_safe=False,
    install_requires=requirements,
)
