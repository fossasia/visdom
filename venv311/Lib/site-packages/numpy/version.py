
"""
Module to expose more detailed version info for the installed `numpy`
"""
version = "2.4.3"
__version__ = version
full_version = version

git_revision = "8bcb2e72e67c343e55165e6064fe6a9dc011e954"
release = 'dev' not in version and '+' not in version
short_version = version.split("+")[0]
