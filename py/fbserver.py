from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

from libfb import parutil

from . import server


if __name__ == "__main__":

    # download JS and CSS:
    install_dir = parutil.get_dir_path('visdom')
    server.download_scripts(
        proxies={
            'http': 'http://fwdproxy:8080',
            'https': 'https://fwdproxy:8080',
        },
        install_dir='%s/py' % install_dir,
    )

    # overwrite static path:
    server.tornado_settings["static_path"] = parutil.get_dir_path('visdom/py/static')
    server.tornado_settings["template_path"] = parutil.get_dir_path('visdom/py/static')

    # run the server:
    server.main()
