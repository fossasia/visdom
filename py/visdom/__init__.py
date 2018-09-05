# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os.path
import requests
import traceback
import threading
import websocket  # type: ignore
import json
import math
import re
import base64
import numpy as np  # type: ignore
from PIL import Image  # type: ignore
import base64 as b64  # type: ignore
import numbers
import six
from six import string_types
from six import BytesIO
from six.moves import urllib
import logging
import warnings
import time
import errno
import io
from functools import wraps
try:
    import bs4  # type: ignore
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


here = os.path.abspath(os.path.dirname(__file__))

try:
    with open(os.path.join(here, 'VERSION')) as version_file:
        __version__ = version_file.read().strip()
except Exception:
    __version__ = 'no_version_file'

try:
    import torchfile  # type: ignore
except BaseException:
    from . import torchfile

try:
    raise ConnectionError()
except NameError:  # python 2 doesn't have ConnectionError
    class ConnectionError(Exception):
        pass
except ConnectionError:
    pass

logging.getLogger('requests').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


def isstr(s):
    return isinstance(s, string_types)


def isnum(n):
    return isinstance(n, numbers.Number)


def isndarray(n):
    return isinstance(n, (np.ndarray))


def nan2none(l):
    for idx, val in enumerate(l):
        if math.isnan(val):
            l[idx] = None
    return l


def from_t7(t, b64=False):
    if b64:
        t = base64.b64decode(t)

    with open('/dev/shm/t7', 'wb') as ff:
        ff.write(t)
        ff.close()

    sf = open('/dev/shm/t7', 'rb')

    return torchfile.T7Reader(sf).read_obj()


def loadfile(filename):
    assert os.path.isfile(filename), 'could not find file %s' % filename
    fileobj = open(filename, 'rb')
    assert fileobj, 'could not open file %s' % filename
    str = fileobj.read()
    fileobj.close()
    return str


def _title2str(opts):
    if opts.get('title'):
        if isnum(opts.get('title')):
            title = str(opts.get('title'))
            logger.warn('Numerical title %s has been casted to a string' %
                        title)
            opts['title'] = title
            return opts
        else:
            return opts


def _scrub_dict(d):
    if type(d) is dict:
        return {k: _scrub_dict(v) for k, v in list(d.items())
                if v is not None and _scrub_dict(v) is not None}
    else:
        return d


def _axisformat(xy, opts):
    fields = ['type', 'label', 'tickmin', 'tickmax', 'tickvals', 'ticklabels',
              'tick', 'tickfont']
    if any(opts.get(xy + i) for i in fields):
        has_ticks = (opts.get(xy + 'tickmin') and opts.get(xy + 'tickmax')) \
            is not None
        return {
            'type': opts.get(xy + 'type'),
            'title': opts.get(xy + 'label'),
            'range': [opts.get(xy + 'tickmin'),
                      opts.get(xy + 'tickmax')] if has_ticks else None,
            'tickvals': opts.get(xy + 'tickvals'),
            'ticktext': opts.get(xy + 'ticklabels'),
            'dtick': opts.get(xy + 'tickstep'),
            'showticklabels': opts.get(xy + 'tick'),
            'tickfont': opts.get(xy + 'tickfont'),
        }


def _axisformat3d(xyz, opts):
    fields = ['type', 'label', 'tickmin', 'tickmax', 'tickvals', 'ticklabels',
              'tick', 'tickfont']
    if any(opts.get(xyz + i) for i in fields):
        has_ticks = (opts.get(xyz + 'tickmin') and opts.get(xyz + 'tickmax')) \
            is not None
        has_step = has_ticks and opts.get(xyz + 'tickstep') is not None
        return {
            'type': opts.get(xyz + 'type'),
            'title': opts.get(xyz + 'label'),
            'range': [opts.get(xyz + 'tickmin'),
                      opts.get(xyz + 'tickmax')] if has_ticks else None,
            'tickvals': opts.get(xyz + 'tickvals'),
            'ticktext': opts.get(xyz + 'ticklabels'),
            'nticks': ((opts.get(xyz + 'tickmax') - opts.get(xyz + 'tickmin'))/
                       opts.get(xyz + 'tickstep')) if has_step else None,
            'tickfont': opts.get(xyz + 'tickfont'),
        }


def _opts2layout(opts, is3d=False):
    layout = {
        'showlegend': opts.get('showlegend', 'legend' in opts),
        'title': opts.get('title'),
        'margin': {
            'l': opts.get('marginleft', 0 if is3d else 60),
            'r': opts.get('marginright', 60),
            't': opts.get('margintop', 20 if is3d else 60),
            'b': opts.get('marginbottom', 0 if is3d else 60),
        }
    }

    if is3d:
        layout['scene'] = {
            'xaxis': _axisformat3d('x', opts),
            'yaxis': _axisformat3d('y', opts),
            'zaxis': _axisformat3d('z', opts),
        }
    else:
        layout['xaxis'] = _axisformat('x', opts)
        layout['yaxis'] = _axisformat('x', opts)

    if opts.get('stacked'):
        layout['barmode'] = 'stack' if opts.get('stacked') else 'group'

    layout_opts = opts.get('layoutopts')
    if layout_opts is not None:
        if 'plotly' in layout_opts:
            layout.update(layout_opts['plotly'])

    return _scrub_dict(layout)


def _markerColorCheck(mc, X, Y, L):
    assert isndarray(mc), 'mc should be a numpy ndarray'
    assert mc.shape[0] == L or (
        mc.shape[0] == X.shape[0] and
        (mc.ndim == 1 or mc.ndim == 2 and mc.shape[1] == 3)), \
        ('marker colors have to be of size `%d` or `%d x 3` ' +
         ' or `%d` or `%d x 3`, but got: %s') % \
        (X.shape[0], X.shape[1], L, L, 'x'.join(map(str, mc.shape)))

    assert (mc >= 0).all(), 'marker colors have to be >= 0'
    assert (mc <= 255).all(), 'marker colors have to be <= 255'
    assert (mc == np.floor(mc)).all(), 'marker colors are assumed to be ints'

    mc = np.uint8(mc)

    if mc.ndim == 1:
        markercolor = ['rgba(0, 0, 255, %s)' % (mc[i] / 255.)
                       for i in range(len(mc))]
    else:
        markercolor = ['#%02x%02x%02x' % (i[0], i[1], i[2]) for i in mc]

    if mc.shape[0] != X.shape[0]:
        markercolor = [markercolor[Y[i] - 1] for i in range(Y.shape[0])]

    ret = {}
    for k, v in enumerate(markercolor):
        ret[Y[k]] = ret.get(Y[k], []) + [v]

    return ret


def _assert_opts(opts):
    if opts.get('color'):
        assert isstr(opts.get('color')), 'color should be a string'

    if opts.get('colormap'):
        assert isstr(opts.get('colormap')), \
            'colormap should be string'

    if opts.get('mode'):
        assert isstr(opts.get('mode')), 'mode should be a string'

    if opts.get('markersymbol'):
        assert isstr(opts.get('markersymbol')), \
            'marker symbol should be string'

    if opts.get('markersize'):
        assert isnum(opts.get('markersize')) \
            and opts.get('markersize') > 0, \
            'marker size should be a positive number'

    if opts.get('columnnames'):
        assert isinstance(opts.get('columnnames'), list), \
            'columnnames should be a table with column names'

    if opts.get('rownames'):
        assert isinstance(opts.get('rownames'), list), \
            'rownames should be a table with row names'

    if opts.get('jpgquality'):
        assert isnum(opts.get('jpgquality')), \
            'JPG quality should be a number'
        assert opts.get('jpgquality') > 0 and opts.get('jpgquality') <= 100, \
            'JPG quality should be number between 0 and 100'

    if opts.get('opacity'):
        assert isnum(opts.get('opacity')), 'opacity should be a number'
        assert 0 <= opts.get('opacity') <= 1, \
            'opacity should be a number between 0 and 1'

    if opts.get('fps'):
        assert isnum(opts.get('fps')), 'fps should be a number'
        assert opts.get('fps') > 0, 'fps must be greater than 0'

    if opts.get('title'):
        assert isstr(opts.get('title')), 'title should be a string'


torch_types = []
try:
    import torch
    torch_types.append(torch.Tensor)
    torch_types.append(torch.nn.Parameter)
except (ImportError, AttributeError):
    pass


def _to_numpy(a):
    if isinstance(a, list):
        return np.array(a)
    if len(torch_types) > 0:
        if isinstance(a, torch.autograd.Variable):
            # For PyTorch < 0.4 comptability.
            warnings.warn(
                "Support for versions of PyTorch less than 0.4 is deprecated and "
                "will eventually be removed.", DeprecationWarning)
            a = a.data
    for kind in torch_types:
        if isinstance(a, kind):
            # For PyTorch < 0.4 comptability, where non-Variable
            # tensors do not have a 'detach' method. Will be removed.
            if hasattr(a, 'detach'):
                a = a.detach()
            return a.cpu().numpy()
    return a


def pytorch_wrap(f):
    @wraps(f)
    def wrapped_f(*args, **kwargs):
        args = (_to_numpy(arg) for arg in args)
        kwargs = {k: _to_numpy(v) for (k, v) in kwargs.items()}
        return f(*args, **kwargs)

    return wrapped_f


class Visdom(object):

    def __init__(
        self,
        server='http://localhost',
        endpoint='events',
        port=8097,
        base_url='/',
        ipv6=True,
        http_proxy_host=None,
        http_proxy_port=None,
        env='main',
        send=True,
        raise_exceptions=None,
        use_incoming_socket=True,
        log_to_filename=None,
    ):
        if '//' not in server:
            self.server_base_name = server
            self.server = 'http://' + server
        else:
            self.server_base_name = server[server.index("//") + 2:]
            self.server = server
        self.endpoint = endpoint
        self.port = port
        # preprocess base_url
        self.base_url = base_url if base_url != "/" else ""
        assert self.base_url == '' or self.base_url.startswith('/'), \
            'base_url should start with /'
        assert self.base_url == '' or not self.base_url.endswith('/'), \
            'base_url should not end with / as it is appended automatically'

        self.ipv6 = ipv6
        self.http_proxy_host = http_proxy_host
        self.http_proxy_port = http_proxy_port
        self.env = env              # default env
        self.send = send
        self.event_handlers = {}  # Haven't registered any events
        self.socket_alive = False
        self.use_socket = use_incoming_socket
        # Flag to indicate whether to raise errors or suppress them
        self.raise_exceptions = raise_exceptions
        self.log_to_filename = log_to_filename

        self._send({
            'eid': env,
        }, endpoint='env/' + env)

        # when talking to a server, get a backchannel
        if send and use_incoming_socket:
            self.setup_socket()
        elif send and not use_incoming_socket:
            logger.warn(
                'Without the incoming socket you cannot receive events from '
                'the server or register event handlers to your Visdom client.'
            )
        # Wait for initialization before starting
        time_spent = 0
        inc = 0.1
        while self.use_socket and not self.socket_alive and time_spent < 5:
            time.sleep(inc)
            time_spent += inc
            inc *= 2
        if time_spent > 5:
            logger.warn(
                'Visdom python client failed to establish socket to get '
                'messages from the server. This feature is optional and '
                'can be disabled by initializing Visdom with '
                '`use_incoming_socket=False`, which will prevent waiting for '
                'this request to timeout.'
            )

    def register_event_handler(self, handler, target):
        assert callable(handler), 'Event handler must be a function'
        assert self.use_socket, 'Must be using the incoming socket to '\
            'register events to web actions'
        if target not in self.event_handlers:
            self.event_handlers[target] = []
        self.event_handlers[target].append(handler)

    def clear_event_handlers(self, target):
        self.event_handlers[target] = []

    def setup_socket(self):
        # Setup socket to server
        def on_message(ws, message):
            message = json.loads(message)
            if 'command' in message:
                # Handle server commands
                if message['command'] == 'alive':
                    if 'data' in message and message['data'] == 'vis_alive':
                        logger.info('Visdom successfully connected to server')
                        self.socket_alive = True
                    else:
                        logger.warn('Visdom server failed handshake, may not '
                                    'be properly connected')
            if 'target' in message:
                for handler in list(
                        self.event_handlers.get(message['target'], [])):
                    handler(message)

        def on_error(ws, error):
            try:
                if error.errno == errno.ECONNREFUSED:
                    logger.info(
                        "Socket refused connection, running socketless")
                    ws.close()
                    self.use_socket = False
                else:
                    logger.error(error)
            except AttributeError:
                logger.error(error)

        def on_close(ws):
            self.socket_alive = False

        def run_socket(*args):
            host_scheme = urllib.parse.urlparse(self.server).scheme
            if host_scheme == "https":
                ws_scheme = "wss"
            else:
                ws_scheme = "ws"
            while self.use_socket:
                try:
                    sock_addr = "{}://{}:{}{}/vis_socket".format(
                        ws_scheme, self.server_base_name, self.port, self.base_url)
                    ws = websocket.WebSocketApp(
                        sock_addr,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close
                    )
                    ws.run_forever(http_proxy_host=self.http_proxy_host,
                                   http_proxy_port=self.http_proxy_port,
                                   ping_timeout=100.0)
                    ws.close()
                except Exception as e:
                    logger.error(
                        'Socket had error {}, attempting restart'.format(e))
                time.sleep(3)

        # Start listening thread
        self.socket_thread = threading.Thread(
            target=run_socket,
            name='Visdom-Socket-Thread'
        )
        self.socket_thread.daemon = True
        self.socket_thread.start()

    # Utils
    def _send(self, msg, endpoint='events', quiet=False, from_log=False):
        """
        This function sends specified JSON request to the Tornado server. This
        function should generally not be called by the user, unless you want to
        build the required JSON yourself. `endpoint` specifies the destination
        Tornado server endpoint for the request.
        """
        if msg.get('eid', None) is None:
            msg['eid'] = self.env

        if not self.send:
            return msg, endpoint

        try:
            r = requests.post(
                "{0}:{1}{2}/{3}".format(self.server, self.port, self.base_url, endpoint),
                data=json.dumps(msg),
            )
            if self.log_to_filename is not None and not from_log:
                if endpoint in ['events', 'update']:
                    if msg['win'] is None:
                        msg['win'] = r.text
                    with open(self.log_to_filename, 'a+') as log_file:
                        log_file.write(json.dumps([
                            endpoint,
                            msg,
                        ]) + '\n')
            return r.text
        except BaseException:
            if self.raise_exceptions:
                raise ConnectionError("Error connecting to Visdom server")
            else:
                if self.raise_exceptions is None:
                    warnings.warn(
                        "Visdom is eventually changing to default to raising "
                        "exceptions rather than ignoring/printing. This change"
                        " is expected to happen by July 2018. Please set "
                        "`raise_exceptions` to False to retain current "
                        "behavior.",
                        PendingDeprecationWarning
                    )
                if not quiet:
                    print("Exception in user code:")
                    print('-' * 60)
                    traceback.print_exc()
                return False

    def save(self, envs):
        """
        This function allows the user to save envs that are alive on the
        Tornado server. The envs can be specified as a table (list) of env ids.
        """
        assert isinstance(envs, list), 'envs should be a list'
        if len(envs) > 0:
            for env in envs:
                assert isstr(env), 'env should be a string'

        return self._send({
            'data': envs,
        }, 'save')

    def get_window_data(self, win=None, env=None):
        """
        This function returns all the window data for a specified window in
        an environment. Use win=None to get all the windows in the given
        environment. Env defaults to main
        """

        return self._send(
            msg={'win': win, 'eid': env},
            endpoint='win_data'
        )

    def close(self, win=None, env=None):
        """
        This function closes a specific window.
        Use `win=None` to close all windows in an env.
        """

        return self._send(
            msg={'win': win, 'eid': env},
            endpoint='close'
        )

    def delete_env(self, env):
        """This function deletes a specific environment."""
        return self._send(
            msg={'eid': env},
            endpoint='delete_env'
        )

    def _win_exists_wrap(self, win, env=None):
        """
        This function returns a string indicating whether
        or not a window exists on the server already. ['true' or 'false']
        Returns False if something went wrong
        """
        assert win is not None

        return self._send({
            'win': win,
            'eid': env,
        }, endpoint='win_exists', quiet=True)

    def get_env_list(self):
        """
        This function returns a list of all of the env names that are currently
        in the server.
        """
        return json.loads(self._send({}, endpoint='env_state', quiet=True))

    def win_exists(self, win, env=None):
        """
        This function returns a bool indicating whether
        or not a window exists on the server already.
        Returns None if something went wrong
        """
        try:
            e = self._win_exists_wrap(win, env)
        except ConnectionError:
            print("Error connecting to Visdom server!")
            return None

        if e == 'true':
            return True
        elif e == 'false':
            return False
        else:
            return None

    def _win_hash_wrap(self, win, env=None):
        """
        This function returns a hash of the contents of
        the window if the window exists.
        Return None otherwise.
        """
        assert win is not None

        return self._send({
            'win': win,
            'env': env,
        }, endpoint='win_hash', quiet=True)

    def win_hash(self, win, env=None):
        """
        This function returns md5 hash of the contents
        of a window if it exists on the server.
        Returns None, otherwise
        """
        try:
            e = self._win_hash_wrap(win, env)
        except ConnectionError:
            print("Error connecting to Visdom server!")
            return None

        if re.match(r"([a-fA-F\d]{32})", e):
            return e

        return None

    def _has_connection(self):
        """
        This function returns a bool indicating whether or
        not the server is connected.
        """
        return (self.win_exists('') is not None) and \
            (self.socket_alive or not self.use_socket)

    def check_connection(self, timeout_seconds=0):
        """
        This function returns a bool indicating whether or
        not the server is connected within some timeout. It waits for
        timeout_seconds before determining if the server responds.
        """
        while not self._has_connection() and timeout_seconds > 0:
            time.sleep(0.1)
            timeout_seconds -= 0.1
            print('waiting')

        return self._has_connection()

    def replay_log(self, log_filename):
        """
        This function takes the contents of a visdom log and replays them to
        the current server to restore the state or handle any missing entries.
        """
        with open(log_filename) as f:
            log_entries = f.readlines()
        for entry in log_entries:
            endpoint, msg = json.loads(entry)
            self._send(msg, endpoint, from_log=True)

    # Content

    def text(self, text, win=None, env=None, opts=None, append=False):
        """
        This function prints text in a box. It takes as input an `text` string.
        No specific `opts` are currently supported.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)
        data = [{'content': text, 'type': 'text'}]

        if append:
            endpoint = 'update'
        else:
            endpoint = 'events'

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'opts': opts,
        }, endpoint=endpoint)

    def properties(self, data, win=None, env=None, opts=None):
        """
        This function shows editable properties in a pane.
        Properties are expected to be a List of Dicts e.g.:
        ```
            properties = [
                {'type': 'text', 'name': 'Text input', 'value': 'initial'},
                {'type': 'number', 'name': 'Number input', 'value': '12'},
                {'type': 'button', 'name': 'Button', 'value': 'Start'},
                {'type': 'checkbox', 'name': 'Checkbox', 'value': True},
                {'type': 'select', 'name': 'Select', 'value': 1,
                 'values': ['Red', 'Green', 'Blue']},
            ]
        ```
        Supported types:
         - text: string
         - number: decimal number
         - button: button labeled with "value"
         - checkbox: boolean value rendered as a checkbox
         - select: multiple values select box
            - `value`: id of selected value (zero based)
            - `values`: list of possible values

        Callback are called on property value update:
         - `event_type`: `"PropertyUpdate"`
         - `propertyId`: position in the `properties` list
         - `value`: new value

        No specific `opts` are currently supported.
        """
        opts = {} if opts is None else opts
        _assert_opts(opts)
        data = [{'content': data, 'type': 'properties'}]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'opts': opts,
        }, endpoint='events')

    @pytorch_wrap
    def svg(self, svgstr=None, svgfile=None, win=None, env=None, opts=None):
        """
        This function draws an SVG object. It takes as input an SVG string or
        the name of an SVG file. The function does not support any
        plot-specific `opts`.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        if svgfile is not None:
            svgstr = str(loadfile(svgfile))

        assert svgstr is not None, 'should specify SVG string or filename'
        svg = re.search('<svg .+</svg>', svgstr, re.DOTALL)
        assert svg is not None, 'could not parse SVG string'
        return self.text(text=svg.group(0), win=win, env=env, opts=opts)

    def matplot(self, plot, opts=None, env=None, win=None):
        """
        This function draws a Matplotlib `plot`. The function supports
        one plot-specific option: `resizable`. When set to `True` the plot
        is resized with the pane. You need `beautifulsoup4` and `lxml`
        packages installed to use this option.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        # write plot to SVG buffer:
        buffer = io.StringIO()
        plot.savefig(buffer, format='svg')
        buffer.seek(0)
        svg = buffer.read()
        buffer.close()

        if opts.get('resizable', False):
            if not BS4_AVAILABLE:
                raise ImportError("No module named 'bs4'")
            else:
                try:
                    soup = bs4.BeautifulSoup(svg, 'xml')
                except bs4.FeatureNotFound as e:
                    six.raise_from(ImportError("No module named 'lxml'"), e)
                height = soup.svg.attrs.pop('height', None)
                width = soup.svg.attrs.pop('width', None)
                svg = str(soup)
        else:
            height = None
            width = None

        # show SVG:
        if 'height' not in opts:
            height = height or re.search('height\="([0-9\.]*)pt"', svg)
            if height is not None:
                opts['height'] = 1.4 * int(math.ceil(float(height.group(1))))
        if 'width' not in opts:
            width = width or re.search('width\="([0-9\.]*)pt"', svg)
            if width is not None:
                opts['width'] = 1.35 * int(math.ceil(float(width.group(1))))
        return self.svg(svgstr=svg, opts=opts, env=env, win=win)

    def plotlyplot(self, figure, win=None, env=None):
        """
        This function draws a Plotly 'Figure' object. It does not explicitly
        take options as it assumes you have already explicitly configured the
        figure's layout.

        Note: You must have the 'plotly' Python package installed to use
        this function.
        """
        try:
            import plotly
            # We do a round-trip of JSON encoding and decoding to make use of
            # the Plotly JSON Encoder. The JSON encoder deals with converting
            # numpy arrays to Python lists and several other edge cases.
            figure_dict = json.loads(
                json.dumps(figure, cls=plotly.utils.PlotlyJSONEncoder))

            # If opts title is not added, the title is not added to the top right of the window.
            # We add the paramater to opts manually if it exists.
            opts = dict()
            if 'title' in figure_dict['layout']:
                opts['title'] = figure_dict['layout']['title']

            return self._send({
                'data': figure_dict['data'],
                'layout': figure_dict['layout'],
                'win': win,
                'eid': env,
                'opts': opts
            })
        except ImportError:
            raise RuntimeError(
                "Plotly must be installed to plot Plotly figures")

    @pytorch_wrap
    def image(self, img, win=None, env=None, opts=None):
        """
        This function draws an img. It takes as input an `CxHxW` or `HxW` tensor
        `img` that contains the image. The array values can be float in [0,1] or
        uint8 in [0, 255].
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)
        opts['width'] = opts.get('width', img.shape[img.ndim - 1])
        opts['height'] = opts.get('height', img.shape[img.ndim - 2])

        nchannels = img.shape[0] if img.ndim == 3 else 1
        if nchannels == 1:
            img = np.squeeze(img)
            img = img[np.newaxis, :, :].repeat(3, axis=0)

        if 'float' in str(img.dtype):
            if img.max() <= 1:
                img = img * 255.
            img = np.uint8(img)

        img = np.transpose(img, (1, 2, 0))
        im = Image.fromarray(img)
        buf = BytesIO()
        im.save(buf, format='PNG')
        b64encoded = b64.b64encode(buf.getvalue()).decode('utf-8')

        data = [{
            'content': {
                'src': 'data:image/png;base64,' + b64encoded,
                'caption': opts.get('caption'),
            },
            'type': 'image',
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'opts': opts,
        })

    @pytorch_wrap
    def images(self, tensor, nrow=8, padding=2,
               win=None, env=None, opts=None):
        """
        Given a 4D tensor of shape (B x C x H x W),
        or a list of images all of the same size,
        makes a grid of images of size (B / nrow, nrow).


        This is a modified from `make_grid()`
        https://github.com/pytorch/vision/blob/master/torchvision/utils.py
        """

        # If list of images, convert to a 4D tensor
        if isinstance(tensor, list):
            tensor = np.stack(tensor, 0)

        if tensor.ndim == 2:  # single image H x W
            tensor = np.expand_dims(tensor, 0)
        if tensor.ndim == 3:  # single image
            if tensor.shape[0] == 1:  # if single-channel, convert to 3-channel
                tensor = np.repeat(tensor, 3, 0)
            return self.image(tensor, win, env, opts)
        if tensor.ndim == 4 and tensor.shape[1] == 1:  # single-channel images
            tensor = np.repeat(tensor, 3, 1)

        # make 4D tensor of images into a grid
        nmaps = tensor.shape[0]
        xmaps = min(nrow, nmaps)
        ymaps = int(math.ceil(float(nmaps) / xmaps))
        height = int(tensor.shape[2] + 2 * padding)
        width = int(tensor.shape[3] + 2 * padding)

        grid = np.ones([3, height * ymaps, width * xmaps])
        k = 0
        for y in range(ymaps):
            for x in range(xmaps):
                if k >= nmaps:
                    break
                h_start = y * height + 1 + padding
                h_end = h_start + tensor.shape[2]
                w_start = x * width + 1 + padding
                w_end = w_start + tensor.shape[3]
                grid[:, h_start:h_end, w_start:w_end] = tensor[k]
                k += 1

        return self.image(grid, win, env, opts)

    @pytorch_wrap
    def audio(self, tensor=None, audiofile=None, win=None, env=None, opts=None):
        """
        This function plays audio. It takes as input the filename of the audio
        file or an `N` tensor containing the waveform (use an `Nx2` matrix for
        stereo audio). The function does not support any plot-specific `opts`.

        The following `opts` are supported:

        - `opts.sample_frequency`: sample frequency (`integer` > 0; default = 44100)
        """
        opts = {} if opts is None else opts
        opts['sample_frequency'] = opts.get('sample_frequency', 44100)
        _title2str(opts)
        _assert_opts(opts)
        assert tensor is not None or audiofile is not None, \
            'should specify audio tensor or file'
        if tensor is not None:
            assert tensor.ndim == 1 or (tensor.ndim == 2 and tensor.shape[1] == 2), \
                'tensor should be 1D vector or 2D matrix with 2 columns'

        if tensor is not None:
            import scipy.io.wavfile # type: ignore
            import tempfile
            audiofile = '/tmp/%s.wav' % next(tempfile._get_candidate_names())
            tensor = np.int16(tensor / np.max(np.abs(tensor)) * 32767)
            scipy.io.wavfile.write(audiofile, opts.get('sample_frequency'), tensor)

        extension = audiofile.split('.')[-1].lower()
        mimetypes = {'wav': 'wav', 'mp3': 'mp3', 'ogg': 'ogg', 'flac': 'flac'}
        mimetype = mimetypes.get(extension)
        assert mimetype is not None, 'unknown audio type: %s' % extension

        bytestr = loadfile(audiofile)
        videodata = """
            <audio controls>
                <source type="audio/%s" src="data:audio/%s;base64,%s">
                Your browser does not support the audio tag.
            </audio>
        """ % (mimetype, mimetype, base64.b64encode(bytestr).decode('utf-8'))
        opts['height'] = 80
        opts['width'] = 330
        return self.text(text=videodata, win=win, env=env, opts=opts)

    @pytorch_wrap
    def video(self, tensor=None, dim='LxHxWxC', videofile=None, win=None, env=None, opts=None):
        """
        This function plays a video. It takes as input the filename of the video
        `videofile` or a `LxHxWxC` or `LxCxHxW`-sized `tensor` containing all the frames of
        the video as input, as specified in `dim`. The function does not support any plot-specific `opts`.

        The following `opts` are supported:

        - `opts.fps`: FPS for the video (`integer` > 0; default = 25)
        """
        opts = {} if opts is None else opts
        opts['fps'] = opts.get('fps', 25)
        _title2str(opts)
        _assert_opts(opts)
        assert tensor is not None or videofile is not None, \
            'should specify video tensor or file'

        if tensor is not None:
            import cv2 # type: ignore
            import tempfile
            assert tensor.ndim == 4, 'video should be in 4D tensor'
            assert dim == 'LxHxWxC' or dim == 'LxCxHxW', 'dimension argument should be LxHxWxC or LxCxHxW'
            if dim == 'LxCxHxW':
                tensor = tensor.transpose([0, 2, 3, 1])
            videofile = '/tmp/%s.ogv' % next(tempfile._get_candidate_names())
            if cv2.__version__.startswith('2'):  # OpenCV 2
                fourcc = cv2.cv.CV_FOURCC(
                    chr(ord('T')),
                    chr(ord('H')),
                    chr(ord('E')),
                    chr(ord('O'))
                )
            elif cv2.__version__.startswith('3'):  # OpenCV 3
                fourcc = cv2.VideoWriter_fourcc(
                    chr(ord('T')),
                    chr(ord('H')),
                    chr(ord('E')),
                    chr(ord('O'))
                )
            writer = cv2.VideoWriter(
                videofile,
                fourcc,
                opts.get('fps'),
                (tensor.shape[2], tensor.shape[1])
            )
            assert writer.isOpened(), 'video writer could not be opened'
            for i in range(tensor.shape[0]):
                # TODO mute opencv on this function call somehow
                writer.write(tensor[i, :, :, :])
            writer.release()
            writer = None

        extension = videofile.split(".")[-1].lower()
        mimetypes = {'mp4': 'mp4', 'ogv': 'ogg', 'avi': 'avi', 'webm': 'webm'}
        mimetype = mimetypes.get(extension)
        assert mimetype is not None, 'unknown video type: %s' % extension

        bytestr = loadfile(videofile)
        videodata = """
            <video controls>
                <source type="video/%s" src="data:video/%s;base64,%s">
                Your browser does not support the video tag.
            </video>
        """ % (mimetype, mimetype, base64.b64encode(bytestr).decode('utf-8'))
        return self.text(text=videodata, win=win, env=env, opts=opts)

    def update_window_opts(self, win, opts, env=None):
        """
        This function allows pushing new options to an existing plot window
        without updating the content
        """
        data_to_send = {
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        }
        return self._send(data_to_send, endpoint='update')

    @pytorch_wrap
    def scatter(self, X, Y=None, win=None, env=None, opts=None, update=None,
                name=None):
        """
        This function draws a 2D or 3D scatter plot. It takes in an `Nx2` or
        `Nx3` tensor `X` that specifies the locations of the `N` points in the
        scatter plot. An optional `N` tensor `Y` containing discrete labels that
        range between `1` and `K` can be specified as well -- the labels will be
        reflected in the colors of the markers.

        `update` can be used to efficiently update the data of an existing plot.
        Use 'append' to append data, 'replace' to use new data, and 'remove' to
        delete the trace that is specified in `name`. If updating a single
        trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).
        Using `update='append'` will create a plot if it doesn't exist
        and append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number`; default = `'10'`)
        - `opts.markercolor` : marker color (`np.array`; default = `None`)
        - `opts.textlabels`  : text label for each point (`list`: default = `None`)
        - `opts.legend`      : `table` containing legend names
        """
        if update == 'remove':
            assert win is not None
            assert name is not None, 'A trace must be specified for deletion'
            assert opts is None, 'Opts cannot be updated on trace deletion'
            data_to_send = {
                'data': [],
                'name': name,
                'delete': True,
                'win': win,
                'eid': env,
            }

            return self._send(data_to_send, endpoint='update')

        elif update is not None:
            assert win is not None, 'Must define a window to update'

            if update == 'append':
                if win is None or not self.win_exists(win, env):
                    update = None
                else:
                    update = 'append'

            # case when X is 1 dimensional and corresponding values on y-axis
            # are passed in parameter Y
            if name:
                assert len(name) >= 0, \
                    'name of trace should be non-empty string'
                assert X.ndim == 1 or X.ndim == 2, 'updating by name should' \
                    'have 1-dim or 2-dim X.'
                if X.ndim == 1:
                    assert Y.ndim == 1, \
                        'update by name should have 1-dim Y when X is 1-dim'
                    assert X.shape[0] == Y.shape[0], \
                        'X and Y should have same shape'
                    X = np.column_stack((X, Y))
                    Y = None

        assert X.ndim == 2, 'X should have two dims'
        assert X.shape[1] == 2 or X.shape[1] == 3, 'X should have 2 or 3 cols'

        if Y is not None:
            Y = np.squeeze(Y)
            assert Y.ndim == 1, 'Y should be one-dimensional'
            assert X.shape[0] == Y.shape[0], 'sizes of X and Y should match'
        else:
            Y = np.ones(X.shape[0], dtype=int)

        assert np.equal(np.mod(Y, 1), 0).all(), 'labels should be integers'
        assert Y.min() == 1, 'labels are assumed to be between 1 and K'

        K = int(Y.max())
        is3d = X.shape[1] == 3

        opts = {} if opts is None else opts
        if opts.get('textlabels') is None:
            opts['mode'] = opts.get('mode', 'markers')
        else:
            opts['mode'] = opts.get('mode', 'markers+text')
        opts['markersymbol'] = opts.get('markersymbol', 'dot')
        opts['markersize'] = opts.get('markersize', 10)

        if opts.get('markercolor') is not None:
            opts['markercolor'] = _markerColorCheck(
                opts['markercolor'], X, Y, K)

        L = opts.get('textlabels')
        if L is not None:
            L = np.squeeze(L)
            assert len(L) == X.shape[0], \
                'textlabels and X should have same shape'

        _title2str(opts)
        _assert_opts(opts)

        if opts.get('legend'):
            assert type(opts['legend']) == list and len(opts['legend']) == K

        data = []
        trace_opts = opts.get('traceopts', {'plotly': {}})['plotly']
        for k in range(1, K + 1):
            ind = np.equal(Y, k)
            if ind.any():
                mc = opts.get('markercolor')
                if 'legend' in opts:
                    trace_name = opts.get('legend')[k - 1]
                elif K == 1 and name is not None:
                    trace_name = name
                else:
                    trace_name = str(k)
                use_gl = opts.get('webgl', False)
                _data = {
                    'x': nan2none(X.take(0, 1)[ind].tolist()),
                    'y': nan2none(X.take(1, 1)[ind].tolist()),
                    'name': trace_name,
                    'type': 'scatter3d' if is3d else (
                        'scattergl' if use_gl else 'scatter'),
                    'mode': opts.get('mode'),
                    'text': L[ind].tolist() if L is not None else None,
                    'textposition': 'right',
                    'marker': {
                        'size': opts.get('markersize'),
                        'symbol': opts.get('markersymbol'),
                        'color': mc[k] if mc is not None else None,
                        'line': {
                            'color': '#000000',
                            'width': 0.5
                        }
                    }
                }
                if opts.get('fillarea'):
                    _data['fill'] = 'tonexty'

                if is3d:
                    _data['z'] = X.take(2, 1)[ind].tolist()

                if trace_name in trace_opts:
                    _data.update(trace_opts[trace_name])

                data.append(_scrub_dict(_data))

        if opts:
            for marker_prop in ['markercolor']:
                if marker_prop in opts:
                    del opts[marker_prop]

        # Only send updates to the layout on the first plot, future updates
        # need to use `update_window_opts`
        data_to_send = {
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts, is3d) if update is None else {},
            'opts': opts,
        }
        endpoint = 'events'
        if update:
            data_to_send['name'] = name
            data_to_send['append'] = update == 'append'
            endpoint = 'update'

        return self._send(data_to_send, endpoint=endpoint)

    @pytorch_wrap
    def line(self, Y, X=None, win=None, env=None, opts=None, update=None,
             name=None):
        """
        This function draws a line plot. It takes in an `N` or `NxM` tensor
        `Y` that specifies the values of the `M` lines (that connect `N` points)
        to plot. It also takes an optional `X` tensor that specifies the
        corresponding x-axis values; `X` can be an `N` tensor (in which case all
        lines will share the same x-axis values) or have the same size as `Y`.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data, and 'remove' to
        delete the trace that is specified in `name`. If updating a
        single trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).
        Using `update='append'` will create a plot if it doesn't exist
        and append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.fillarea`    : fill area below line (`boolean`)
        - `opts.markers`     : show markers (`boolean`; default = `false`)
        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number`; default = `'10'`)
        - `opts.legend`      : `table` containing legend names

        If `update` is specified, the figure will be updated without
        creating a new plot -- this can be used for efficient updating.
        """
        if update is not None:
            if update == 'remove':
                return self.scatter(X=None, Y=None, opts=opts, win=win,
                                    env=env, update=update, name=name)
            else:
                assert X is not None, 'must specify x-values for line update'
        assert Y.ndim == 1 or Y.ndim == 2, 'Y should have 1 or 2 dim'
        assert Y.shape[-1] > 0, 'must plot one line at least'

        if X is not None:
            assert X.ndim == 1 or X.ndim == 2, 'X should have 1 or 2 dim'
        else:
            X = np.linspace(0, 1, Y.shape[0])

        if Y.ndim == 2 and Y.shape[1] == 1:
                Y = Y.reshape(Y.shape[0])
                X = X.reshape(X.shape[0])

        if Y.ndim == 2 and X.ndim == 1:
            X = np.tile(X, (Y.shape[1], 1)).transpose()

        assert X.shape == Y.shape, 'X and Y should be the same shape'

        opts = {} if opts is None else opts
        opts['markers'] = opts.get('markers', False)
        opts['fillarea'] = opts.get('fillarea', False)
        opts['mode'] = 'lines+markers' if opts.get('markers') else 'lines'

        _title2str(opts)
        _assert_opts(opts)

        if Y.ndim == 1:
            linedata = np.column_stack((X, Y))
        else:
            linedata = np.column_stack((X.ravel(order='F'), Y.ravel(order='F')))

        labels = None
        if Y.ndim == 2:
            labels = np.arange(1, Y.shape[1] + 1)
            labels = np.tile(labels, (Y.shape[0], 1)).ravel(order='F')

        return self.scatter(X=linedata, Y=labels, opts=opts, win=win, env=env,
                            update=update, name=name)

    @pytorch_wrap
    def heatmap(self, X, win=None, env=None, opts=None):
        """
        This function draws a heatmap. It takes as input an `NxM` tensor `X`
        that specifies the value at each location in the heatmap.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        - `opts.columnnames`: `table` containing x-axis labels
        - `opts.rownames`: `table` containing y-axis labels
        """

        assert X.ndim == 2, 'data should be two-dimensional'
        opts = {} if opts is None else opts
        opts['xmin'] = opts.get('xmin', np.asscalar(X.min()))
        opts['xmax'] = opts.get('xmax', np.asscalar(X.max()))
        opts['colormap'] = opts.get('colormap', 'Viridis')
        _title2str(opts)
        _assert_opts(opts)

        if opts.get('columnnames') is not None:
            assert len(opts['columnnames']) == X.shape[1], \
                'number of column names should match number of columns in X'

        if opts.get('rownames') is not None:
            assert len(opts['rownames']) == X.shape[0], \
                'number of row names should match number of rows in X'

        data = [{
            'z': X.tolist(),
            'x': opts.get('columnnames'),
            'y': opts.get('rownames'),
            'zmin': opts.get('xmin'),
            'zmax': opts.get('xmax'),
            'type': 'heatmap',
            'colorscale': opts.get('colormap'),
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        })

    @pytorch_wrap
    def bar(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a regular, stacked, or grouped bar plot. It takes as
        input an `N` or `NxM` tensor `X` that specifies the height of each
        bar. If `X` contains `M` columns, the values corresponding to each row
        are either stacked or grouped (dependending on how `opts.stacked` is
        set). In addition to `X`, an (optional) `N` tensor `Y` can be specified
        that contains the corresponding x-axis values.

        The following plot-specific `opts` are currently supported:

        - `opts.rownames`: `table` containing x-axis labels
        - `opts.stacked` : stack multiple columns in `X`
        - `opts.legend`  : `table` containing legend labels
        """
        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, 'X should be one or two-dimensional'
        if X.ndim == 1:
            if opts is not None and opts.get('legend') is not None:
                X = X[None, :]
                assert opts.get('rownames') is None, \
                    'both rownames and legend cannot be specified \
                    for one-dimensional X values'
            else:
                X = X[:, None]
        if Y is not None:
            Y = np.squeeze(Y)
            assert Y.ndim == 1, 'Y should be one-dimensional'
            assert len(X) == len(Y), 'sizes of X and Y should match'
        else:
            Y = np.arange(1, len(X) + 1)

        opts = {} if opts is None else opts
        opts['stacked'] = opts.get('stacked', False)

        _title2str(opts)
        _assert_opts(opts)

        if opts.get('rownames') is not None:
            assert len(opts['rownames']) == X.shape[0], \
                'number of row names should match number of rows in X'

        if opts.get('legend') is not None:
            assert len(opts['legend']) == X.shape[1], \
                'number of legend labels must match number of columns in X'

        data = []
        for k in range(X.shape[1]):
            _data = {
                'y': X.take(k, 1).tolist(),
                'x': opts.get('rownames', Y.tolist()),
                'type': 'bar',
            }
            if opts.get('legend'):
                _data['name'] = opts['legend'][k]
            data.append(_data)

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        })

    @pytorch_wrap
    def histogram(self, X, win=None, env=None, opts=None):
        """
        This function draws a histogram of the specified data. It takes as input
        an `N` tensor `X` that specifies the data of which to construct the
        histogram.

        The following plot-specific `opts` are currently supported:

        - `opts.numbins`: number of bins (`number`; default = 30)
        """

        X = np.squeeze(X)
        assert X.ndim == 1, 'X should be one-dimensional'

        opts = {} if opts is None else opts
        opts['numbins'] = opts.get('numbins', min(30, len(X)))
        _title2str(opts)
        _assert_opts(opts)

        minx, maxx = X.min(), X.max()
        bins = np.histogram(X, bins=opts['numbins'], range=(minx, maxx))[0]
        linrange = np.linspace(minx, maxx, opts['numbins'])

        return self.bar(
            X=bins,
            Y=linrange,
            opts=opts,
            win=win,
            env=env
        )

    @pytorch_wrap
    def boxplot(self, X, win=None, env=None, opts=None):
        """
        This function draws boxplots of the specified data. It takes as input
        an `N` or an `NxM` tensor `X` that specifies the `N` data values of
        which to construct the `M` boxplots.

        The following plot-specific `opts` are currently supported:
        - `opts.legend`: labels for each of the columns in `X`
        """

        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, 'X should be one or two-dimensional'
        if X.ndim == 1:
            X = X[:, None]

        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        if opts.get('legend') is not None:
            assert len(opts['legend']) == X.shape[1], \
                'number of legened labels must match number of columns'

        data = []
        for k in range(X.shape[1]):
            _data = {
                'y': X.take(k, 1).tolist(),
                'type': 'box',
            }
            if opts.get('legend'):
                _data['name'] = opts['legend'][k]
            else:
                _data['name'] = 'column ' + str(k)

            data.append(_data)

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        })

    @pytorch_wrap
    def _surface(self, X, stype, win=None, env=None, opts=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        `stype` is 'contour' (2D) or 'surface' (3D).

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """
        X = np.squeeze(X)
        assert X.ndim == 2, 'X should be two-dimensional'

        opts = {} if opts is None else opts
        opts['xmin'] = float(opts.get('xmin', X.min()))
        opts['xmax'] = float(opts.get('xmax', X.max()))
        opts['colormap'] = opts.get('colormap', 'Viridis')
        _title2str(opts)
        _assert_opts(opts)

        data = [{
            'z': X.tolist(),
            'cmin': opts['xmin'],
            'cmax': opts['xmax'],
            'type': stype,
            'colorscale': opts['colormap']
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(
                opts, is3d=True if stype == 'surface' else False),
            'opts': opts,
        })

    @pytorch_wrap
    def surf(self, X, win=None, env=None, opts=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        return self._surface(X=X, stype='surface', opts=opts, win=win, env=env)

    @pytorch_wrap
    def contour(self, X, win=None, env=None, opts=None):
        """
        This function draws a contour plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the contour plot.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        return self._surface(X=X, stype='contour', opts=opts, win=win, env=env)

    @pytorch_wrap
    def quiver(self, X, Y, gridX=None, gridY=None,
               win=None, env=None, opts=None):
        """
        This function draws a quiver plot in which the direction and length of the
        arrows is determined by the `NxM` tensors `X` and `Y`. Two optional `NxM`
        tensors `gridX` and `gridY` can be provided that specify the offsets of
        the arrows; by default, the arrows will be done on a regular grid.

        The following `opts` are supported:

        - `opts.normalize`:  length of longest arrows (`number`)
        - `opts.arrowheads`: show arrow heads (`boolean`; default = `true`)
        """

        # assertions:
        assert X.ndim == 2, 'X should be two-dimensional'
        assert Y.ndim == 2, 'Y should be two-dimensional'
        assert Y.shape == X.shape, 'X and Y should have the same size'

        # make sure we have a grid:
        N, M = X.shape[0], X.shape[1]
        if gridX is None:
            gridX = np.broadcast_to(
                np.expand_dims(np.arange(0, N), axis=1), (N, M))
        if gridY is None:
            gridY = np.broadcast_to(
                np.expand_dims(np.arange(0, M), axis=0), (N, M))
        assert gridX.shape == X.shape, 'X and gridX should have the same size'
        assert gridY.shape == Y.shape, 'Y and gridY should have the same size'

        # default options:
        opts = {} if opts is None else opts
        opts['mode'] = 'lines'
        opts['arrowheads'] = opts.get('arrowheads', True)
        _title2str(opts)
        _assert_opts(opts)

        # normalize vectors to unit length:
        if opts.get('normalize', False):
            assert isinstance(opts['normalize'], numbers.Number) and \
                opts['normalize'] > 0, \
                'opts.normalize should be positive number'
            magnitude = np.sqrt(np.add(np.multiply(X, X),
                                       np.multiply(Y, Y))).max()
            X = X / (magnitude / opts['normalize'])
            Y = Y / (magnitude / opts['normalize'])

        # interleave X and Y with copies / NaNs to get lines:
        nans = np.full((X.shape[0], X.shape[1]), np.nan).flatten()
        tipX = gridX + X
        tipY = gridY + Y
        dX = np.column_stack((gridX.flatten(), tipX.flatten(), nans))
        dY = np.column_stack((gridY.flatten(), tipY.flatten(), nans))

        # convert data to scatter plot format:
        dX = np.resize(dX, (dX.shape[0] * 3, 1))
        dY = np.resize(dY, (dY.shape[0] * 3, 1))
        data = np.column_stack((dX.flatten(), dY.flatten()))

        # add arrow heads:
        if opts['arrowheads']:

            # compute tip points:
            alpha = 0.33  # size of arrow head relative to vector length
            beta = 0.33   # width of the base of the arrow head
            Xbeta = (X + 1e-5) * beta
            Ybeta = (Y + 1e-5) * beta
            lX = np.add(-alpha * np.add(X, Ybeta), tipX)
            rX = np.add(-alpha * np.add(X, -Ybeta), tipX)
            lY = np.add(-alpha * np.add(Y, -Xbeta), tipY)
            rY = np.add(-alpha * np.add(Y, Xbeta), tipY)

            # add to data:
            hX = np.column_stack((lX.flatten(), tipX.flatten(),
                                  rX.flatten(), nans))
            hY = np.column_stack((lY.flatten(), tipY.flatten(),
                                  rY.flatten(), nans))
            hX = np.resize(hX, (hX.shape[0] * 4, 1))
            hY = np.resize(hY, (hY.shape[0] * 4, 1))
            data = np.concatenate((data, np.column_stack(
                (hX.flatten(), hY.flatten()))), axis=0)

        # generate scatter plot:
        return self.scatter(X=data, opts=opts, win=win, env=env)

    @pytorch_wrap
    def stem(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a stem plot. It takes as input an `N` or `NxM`tensor
        `X` that specifies the values of the `N` points in the `M` time series.
        An optional `N` or `NxM` tensor `Y` containing timestamps can be given
        as well; if `Y` is an `N` tensor then all `M` time series are assumed to
        have the same timestamps.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.legend`  : `table` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, 'X should be one or two-dimensional'
        if X.ndim == 1:
            X = X[:, None]

        if Y is None:
            Y = np.arange(1, X.shape[0] + 1)
        if Y.ndim == 1:
            Y = Y[:, None]
        assert Y.shape[0] == X.shape[0], 'number of rows in X and Y must match'
        assert Y.shape[1] == 1 or Y.shape[1] == X.shape[1], \
            'Y should be a single column or the same number of columns as X'

        if Y.shape[1] < X.shape[1]:
            Y = np.tile(Y, (1, X.shape[1]))

        Z = np.zeros((Y.shape))  # Zeros
        with np.errstate(divide='ignore', invalid='ignore'):
            N = Z / Z                # NaNs
        X = np.column_stack((Z, X, N)).reshape((X.shape[0] * 3, X.shape[1]))
        Y = np.column_stack((Y, Y, N)).reshape((Y.shape[0] * 3, Y.shape[1]))

        data = np.column_stack((Y.flatten(), X.flatten()))
        labels = np.arange(1, X.shape[1] + 1)[None, :]
        labels = np.tile(labels, (X.shape[0], 1)).flatten()

        opts = {} if opts is None else opts
        opts['mode'] = 'lines'
        _title2str(opts)
        _assert_opts(opts)

        return self.scatter(X=data, Y=labels, opts=opts, win=win, env=env)

    @pytorch_wrap
    def pie(self, X, win=None, env=None, opts=None):
        """
        This function draws a pie chart based on the `N` tensor `X`.

        The following `opts` are supported:

        - `opts.legend`: `table` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1, 'X should be one-dimensional'
        assert np.all(np.greater_equal(X, 0)), \
            'X cannot contain negative values'

        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        data = [{
            'values': X.tolist(),
            'labels': opts.get('legend'),
            'type': 'pie',
        }]
        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        })

    @pytorch_wrap
    def mesh(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a mesh plot from a set of vertices defined in an
        `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or
        `Mx3` matrix `Y`.

        The following `opts` are supported:

        - `opts.color`: color (`string`)
        - `opts.opacity`: opacity of polygons (`number` between 0 and 1)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        X = np.asarray(X)
        assert X.ndim == 2, 'X must have 2 dimensions'
        assert X.shape[1] == 2 or X.shape[1] == 3, 'X must have 2 or 3 columns'
        is3d = X.shape[1] == 3

        ispoly = Y is not None
        if ispoly:
            Y = np.asarray(Y)
            assert Y.ndim == 2, 'Y must have 2 dimensions'
            assert Y.shape[1] == X.shape[1], \
                'X and Y must have same number of columns'

        data = [{
            'x': X[:, 0].tolist(),
            'y': X[:, 1].tolist(),
            'z': X[:, 2].tolist() if is3d else None,
            'i': Y[:, 0].tolist() if ispoly else None,
            'j': Y[:, 1].tolist() if ispoly else None,
            'k': Y[:, 2].tolist() if is3d and ispoly else None,
            'color': opts.get('color'),
            'opacity': opts.get('opacity'),
            'type': 'mesh3d' if is3d else 'mesh',
        }]
        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts),
            'opts': opts,
        })
