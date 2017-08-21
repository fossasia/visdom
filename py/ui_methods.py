import tornado.web

def make_static_url(settings, path, include_version=True):
    """Constructs a versioned url for the given path.
    This method may be overridden in subclasses (but note that it
    is a class method rather than an instance method).  Subclasses
    are only required to implement the signature
    ``make_static_url(cls, settings, path)``; other keyword
    arguments may be passed through `~RequestHandler.static_url`
    but are not standard.
    ``settings`` is the `Application.settings` dictionary.  ``path``
    is the static path being requested.  The url returned should be
    relative to the current host.
    ``include_version`` determines whether the generated URL should
    include the query string containing the version hash of the
    file corresponding to the given ``path``.
    """
    cls = tornado.web.StaticFileHandler
    url = settings.get('scripts_url_prefix', '/scripts/') + path
    if not include_version:
        return url

    version_hash = cls.get_version(settings, path)
    if not version_hash:
        return url

    return '%s?v=%s' % (url, version_hash)

def scripts_url(self, data, include_host=None, **kwargs):
    self.require_setting("static_path", "static_url")
    get_url = make_static_url

    if include_host is None:
        include_host = getattr(self, "include_host", False)

    if include_host:
        base = self.request.protocol + "://" + self.request.host
    else:
        base = ""

    return base + get_url(self.settings, data, **kwargs)
