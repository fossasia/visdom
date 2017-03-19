from distutils.core import setup

readme = open('README.md').read()

requirements = [
    'numpy',
    'pillow',
    'requests',
    'tornado',
    'pyzmq',
    'six',
]

setup(
    # Metadata
    name='visdom',
    version='0.1.01',
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
)
