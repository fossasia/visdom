# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Server"""

from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import math
import json
import logging
import traceback
import os
import inspect
import time
import getpass
import argparse
import copy
import visdom

from os.path import expanduser
from zmq.eventloop import ioloop
ioloop.install()  # Needs to happen before any tornado imports!

import tornado.ioloop     # noqa E402: gotta install ioloop first
import tornado.web        # noqa E402: gotta install ioloop first
import tornado.websocket  # noqa E402: gotta install ioloop first
import tornado.escape     # noqa E402: gotta install ioloop first

parser = argparse.ArgumentParser(description='Start the visdom server.')
parser.add_argument('-port', metavar='port', type=int, default=8097,
                    help='port to run the server on.')
parser.add_argument('-env_path', metavar='env_path', type=str,
                    default='%s/.visdom/' % expanduser("~"),
                    help='path to serialized session to reload.')
parser.add_argument('-logging_level', metavar='logger_level', default='INFO',
                    help='logging level (default = INFO). Can take logging '
                         'level name or int (example: 20)')
FLAGS = parser.parse_args()

LAYOUT_FILE = 'layouts.json'

try:
    logging_level = int(FLAGS.logging_level)
except (ValueError,):
    try:
        logging_level = logging._checkLevel(FLAGS.logging_level)
    except ValueError:
        raise KeyError(
            "Invalid logging level : {0}".format(FLAGS.logging_level)
        )

logging.getLogger().setLevel(logging_level)


def get_rand_id():
    return str(hex(int(time.time() * 10000000))[2:])


def ensure_dir_exists(path):
    """Make sure the parent dir exists for path so we can write a file."""
    try:
        os.makedirs(os.path.dirname(path))
    except OSError as e1:
        assert e1.errno == 17  # errno.EEXIST
        pass


def get_path(filename):
    """Get the path to an asset."""
    cwd = os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe())))
    return os.path.join(cwd, filename)


def escape_eid(eid):
    """Replace slashes with underscores, to avoid recognizing them
    as directories.
    """

    return eid.replace('/', '_')


def extract_eid(args):
    """Extract eid from args. If eid does not exist in args,
    it returns 'main'."""

    eid = 'main' if args.get('eid') is None else args.get('eid')
    return escape_eid(eid)


tornado_settings = {
    "autoescape": None,
    "debug": "/dbg/" in __file__,
    "static_path": get_path('static'),
    "template_path": get_path('static'),
    "compiled_template_cache": False
}


def serialize_env(state, eids):
    env_ids = [i for i in eids if i in state]
    for env_id in env_ids:
        env_path = os.path.join(FLAGS.env_path, "{0}.json".format(env_id))
        open(env_path, 'w').write(json.dumps(state[env_id]))
    return env_ids


def serialize_all(state):
    serialize_env(state, list(state.keys()))


class Application(tornado.web.Application):
    def __init__(self):
        self.state = {}
        self.subs = {}
        self.sources = {}

        # reload state
        ensure_dir_exists(FLAGS.env_path)
        env_jsons = [i for i in os.listdir(FLAGS.env_path) if '.json' in i]

        for env_json in env_jsons:
            env_path = os.path.join(FLAGS.env_path, env_json)
            env_data = tornado.escape.json_decode(open(env_path, 'r').read())
            eid = env_json.replace('.json', '')
            self.state[eid] = {'jsons': env_data['jsons'],
                               'reload': env_data['reload']}

        if 'main' not in self.state and 'main.json' not in env_jsons:
            self.state['main'] = {'jsons': {}, 'reload': {}}
            serialize_env(self.state, ['main'])

        handlers = [
            (r"/events", PostHandler, {'app': self}),
            (r"/update", UpdateHandler, {'app': self}),
            (r"/close", CloseHandler, {'app': self}),
            (r"/socket", SocketHandler, {'app': self}),
            (r"/vis_socket", VisSocketHandler, {'app': self}),
            (r"/env/(.*)", EnvHandler, {'app': self}),
            (r"/save", SaveHandler, {'app': self}),
            (r"/error/(.*)", ErrorHandler, {'app': self}),
            (r"/win_exists", ExistsHandler, {'app': self}),
            (r"/win_data", DataHandler, {'app': self}),
            (r"/(.*)", IndexHandler, {'app': self}),
        ]
        super(Application, self).__init__(handlers, **tornado_settings)


def broadcast_envs(handler, target_subs=None):
    if target_subs is None:
        target_subs = handler.subs.values()
    for sub in target_subs:
        sub.write_message(json.dumps(
            {'command': 'env_update', 'data': list(handler.state.keys())}
        ))


def send_to_sources(handler, msg):
    target_sources = handler.sources.values()
    for source in target_sources:
        source.write_message(json.dumps(msg))


class VisSocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    def check_origin(self, origin):
        return True

    def open(self):
        self.sid = str(hex(int(time.time() * 10000000))[2:])
        if self not in list(self.sources.values()):
            self.eid = 'main'
            self.sources[self.sid] = self
        logging.info('Opened visdom socket from ip: {}'.format(
            self.request.remote_ip))

        self.write_message(
            json.dumps({'command': 'alive', 'data': 'vis_alive'}))

    def on_message(self, message):
        logging.info('from visdom client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')
        if cmd == 'echo':
            for sub in self.sources.values():
                sub.write_message(json.dumps(msg))

    def on_close(self):
        if self in list(self.sources.values()):
            self.sources.pop(self.sid, None)


class SocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, app):
        self.layouts = self.load_layouts()
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.broadcast_layouts()

    def check_origin(self, origin):
        return True

    def broadcast_layouts(self, target_subs=None):
        if target_subs is None:
            target_subs = self.subs.values()
        for sub in target_subs:
            sub.write_message(json.dumps(
                {'command': 'layout_update', 'data': self.layouts}
            ))

    def save_layouts(self):
        layout_filepath = os.path.join(FLAGS.env_path, 'view', LAYOUT_FILE)
        with open(layout_filepath, 'w') as fn:
            fn.write(self.layouts)

    def load_layouts(self):
        layout_filepath = os.path.join(FLAGS.env_path, 'view', LAYOUT_FILE)
        ensure_dir_exists(layout_filepath)
        if os.path.isfile(layout_filepath):
            with open(layout_filepath, 'r') as fn:
                return fn.read()
        else:
            return ""

    def open(self):
        self.sid = str(hex(int(time.time() * 10000000))[2:])
        if self not in list(self.subs.values()):
            self.eid = 'main'
            self.subs[self.sid] = self
        logging.info(
            'Opened new socket from ip: {}'.format(self.request.remote_ip))

        self.write_message(
            json.dumps({'command': 'register', 'data': self.sid}))
        self.broadcast_layouts([self])
        broadcast_envs(self, [self])

    def on_message(self, message):
        logging.info('from web client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')
        if cmd == 'close':
            if 'data' in msg and 'eid' in msg:
                logging.info('closing window {}'.format(msg['data']))
                p_data = self.state[msg['eid']]['jsons'].pop(msg['data'], None)
                event = {
                    'event_type': 'Close',
                    'target': msg['data'],
                    'eid': msg['eid'],
                    'pane_data': p_data,
                }
                send_to_sources(self, event)
        elif cmd == 'save':
            # save localStorage window metadata
            if 'data' in msg and 'eid' in msg:
                msg['eid'] = escape_eid(msg['eid'])
                self.state[msg['eid']] = \
                    copy.deepcopy(self.state[msg['prev_eid']])
                self.state[msg['eid']]['reload'] = msg['data']
                self.eid = msg['eid']
                serialize_env(self.state, [self.eid])
        elif cmd == 'delete_env':
            if 'eid' in msg:
                logging.info('closing environment {}'.format(msg['eid']))
                del self.state[msg['eid']]
                p = os.path.join(FLAGS.env_path, "{0}.json".format(msg['eid']))
                os.remove(p)
                broadcast_envs(self)
        elif cmd == 'save_layouts':
            if 'data' in msg:
                self.layouts = msg.get('data')
                self.save_layouts()
                self.broadcast_layouts()
        elif cmd == 'forward_to_vis':
            packet = msg.get('data')
            environment = self.state[packet['eid']]
            packet['pane_data'] = environment['jsons'][packet['target']]
            send_to_sources(self, msg.get('data'))

    def on_close(self):
        if self in list(self.subs.values()):
            self.subs.pop(self.sid, None)


class BaseHandler(tornado.web.RequestHandler):
    def __init__(self, *request, **kwargs):
        self.include_host = True
        super(BaseHandler, self).__init__(*request, **kwargs)

    def write_error(self, status_code, **kwargs):
        logging.error("ERROR: %s: %s" % (status_code, kwargs))
        if self.settings.get("debug") and "exc_info" in kwargs:
            logging.error("rendering error page")
            import traceback
            exc_info = kwargs["exc_info"]
            # exc_info is a tuple consisting of:
            # 1. The class of the Exception
            # 2. The actual Exception that was thrown
            # 3. The traceback opbject
            try:
                params = {
                    'error': exc_info[1],
                    'trace_info': traceback.format_exception(*exc_info),
                    'request': self.request.__dict__
                }

                self.render("error.html", **params)
                logging.error("rendering complete")
            except Exception as e:
                logging.error(e)


def update_window(p, args):
    """Adds new args to a window if they exist"""
    content = p['content']
    layout = content['layout']
    layout.update(args.get('layout', {}))
    opts = args.get('opts', {})
    for opt_name, opt_val in opts.items():
        if opt_name in p:
            p[opt_name] = opt_val

    if 'legend' in opts:
        pdata = p['content']['data']
        for i, d in enumerate(pdata):
            d['name'] = opts['legend'][i]
    return p


def window(args):
    """ Build a window dict structure for sending to client """
    uid = args.get('win', 'window_' + get_rand_id())
    if uid is None:
        uid = 'window_' + get_rand_id()
    opts = args.get('opts', {})

    ptype = args['data'][0]['type']

    p = {
        'command': 'window',
        'id': str(uid),
        'title': opts.get('title', ''),
        'inflate': opts.get('inflate', True),
        'width': opts.get('width'),
        'height': opts.get('height'),
        'contentID': get_rand_id(),   # to detected updated windows
    }

    if ptype in ['image', 'text']:
        p.update({'content': args['data'][0]['content'], 'type': ptype})
    else:
        p['content'] = {'data': args['data'], 'layout': args['layout']}
        p['type'] = 'plot'

    return p


def broadcast(self, msg, eid):
    for s in self.subs:
        if self.subs[s].eid == eid:
            self.subs[s].write_message(msg)


def register_window(self, p, eid):
    # in case env doesn't exist
    self.state[eid] = self.state.get(eid, {'jsons': {}, 'reload': {}})
    env = self.state[eid]['jsons']

    if p['id'] in env:
        p['i'] = env[p['id']]['i']
    else:
        p['i'] = len(env)

    env[p['id']] = p

    broadcast(self, p, eid)
    broadcast_envs(self)
    self.write(p['id'])


def unpack_lua(req_args):
    if req_args['is_table']:
        if isinstance(req_args['val'], dict):
            return {k: unpack_lua(v) for (k, v) in req_args['val'].items()}
        else:
            return [unpack_lua(v) for v in req_args['val']]
    elif req_args['is_tensor']:
        return visdom.from_t7(req_args['val'], b64=True)
    else:
        return req_args['val']


class PostHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.vis = visdom.Visdom(port=FLAGS.port, send=False)
        self.handlers = {
            'update': UpdateHandler,
            'save': SaveHandler,
            'close': CloseHandler,
            'win_exists': ExistsHandler,
            'delete_env': DeleteEnvHandler,
        }

    def func(self, req):
        args, kwargs = req['args'], req.get('kwargs', {})

        args = (unpack_lua(a) for a in args)

        for k in kwargs:
            v = kwargs[k]
            kwargs[k] = unpack_lua(v)

        func = getattr(self.vis, req['func'])

        return func(*args, **kwargs)

    def post(self):
        req = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )

        if req.get('func') is not None:
            try:
                req, endpoint = self.func(req)
                if (endpoint != 'events'):
                    # Process the request using the proper handler
                    self.handlers[endpoint].wrap_func(self, req)
                    return
            except Exception:
                # get traceback and send it back
                print(traceback.format_exc())
                return self.write(traceback.format_exc())

        eid = extract_eid(req)
        p = window(req)

        register_window(self, p, eid)


class ExistsHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if args['win'] in handler.state[eid]['jsons']:
            handler.write('true')
        else:
            handler.write('false')

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class UpdateHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    # TODO remove when updateTrace is to be deprecated
    @staticmethod
    def update_updateTrace(p, args):
        pdata = p['content']['data']

        new_data = args['data']
        name = args.get('name')
        append = args.get('append')

        idxs = list(range(len(pdata)))

        if name is not None:
            assert len(new_data['x']) == 1
            idxs = [i for i in idxs if pdata[i]['name'] == name]

        # inject new trace
        if len(idxs) == 0:
            idx = len(pdata)
            pdata.append(dict(pdata[0]))   # plot is not empty, clone an entry
            pdata[idx]['name'] = name
            idxs = [idx]
            append = False
            if 'marker' in new_data:
                pdata[idx]['marker']['color'] = new_data['marker']

        for n, idx in enumerate(idxs):    # update traces
            if all(math.isnan(i) or i is None for i in new_data['x'][n]):
                continue

            pdata[idx]['x'] = (pdata[idx]['x'] + new_data['x'][n]) if append \
                else new_data['x'][n]
            pdata[idx]['y'] = (pdata[idx]['y'] + new_data['y'][n]) if append \
                else new_data['y'][n]

        return p

    @staticmethod
    def update(p, args):
        # Update text in window, separated by a line break
        if p['type'] == 'text':
            p['content'] += "<br>" + args['data'][0]['content']
            return p

        pdata = p['content']['data']

        new_data = args.get('data')
        # TODO remove when updateTrace is deprecated
        if isinstance(new_data, dict):
            return UpdateHandler.update_updateTrace(p, args)
        p = update_window(p, args)
        name = args.get('name')
        if name is None and new_data is None:
            return p  # we only updated the opts or layout
        append = args.get('append')

        idxs = list(range(len(pdata)))

        if name is not None:
            assert len(new_data) == 1 or args.get('delete')
            idxs = [i for i in idxs if pdata[i]['name'] == name]

        # Delete a trace
        if args.get('delete'):
            for idx in idxs:
                del pdata[idx]
            return p

        # inject new trace
        if len(idxs) == 0:
            idx = len(pdata)
            pdata.append(dict(pdata[0]))  # plot is not empty, clone an entry
            idxs = [idx]
            append = False
            pdata[idx] = new_data[0]
            for k, v in new_data[0].items():
                pdata[idx][k] = v
            pdata[idx]['name'] = name
            return p

        # Update traces
        for n, idx in enumerate(idxs):
            if all(math.isnan(i) or i is None for i in new_data[n]['x']):
                continue
            # handle data for plotting
            for axis in ['x', 'y']:
                pdata[idx][axis] = (pdata[idx][axis] + new_data[n][axis]) \
                    if append else new_data[n][axis]

            # handle marker properties
            if 'marker' not in new_data[n]:
                continue
            if 'marker' not in pdata[idx]:
                pdata[idx]['marker'] = {}
            pdata_marker = pdata[idx]['marker']
            for marker_prop in ['color']:
                if marker_prop not in new_data[n]['marker']:
                    continue
                if marker_prop not in pdata[idx]['marker']:
                    pdata[idx]['marker'][marker_prop] = []
                pdata_marker[marker_prop] = (
                    pdata_marker[marker_prop] +
                    new_data[n]['marker'][marker_prop]) if append else \
                    new_data[n]['marker'][marker_prop]

        return p

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if args['win'] not in handler.state[eid]['jsons']:
            handler.write('win does not exist')
            return

        p = handler.state[eid]['jsons'][args['win']]

        if not (p['type'] == 'text' or
                p['content']['data'][0]['type'] == 'scatter'):
            handler.write('win is not scatter or text')
            return

        p = UpdateHandler.update(p, args)

        p['contentID'] = get_rand_id()
        broadcast(handler, p, eid)
        handler.write(p['id'])

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class CloseHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        win = args.get('win')

        keys = \
            list(handler.state[eid]['jsons'].keys()) if win is None else [win]
        for win in keys:
            handler.state[eid]['jsons'].pop(win, None)
            broadcast(
                handler, json.dumps({'command': 'close', 'data': win}), eid
            )

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class DeleteEnvHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        if eid is not None:
            del handler.state[eid]
            p = os.path.join(FLAGS.env_path, "{0}.json".format(eid))
            os.remove(p)
            broadcast_envs(handler)

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


def load_env(state, eid, socket):
    """ load an environment to a client by socket """

    env = {}
    if eid in state:
        env = state.get(eid)
    else:
        p = os.path.join(FLAGS.env_path, eid.strip(), '.json')
        if os.path.exists(p):
            env = tornado.escape.json_decode(open(p, 'r').read())
            state[eid] = env

    if 'reload' in env:
        socket.write_message(
            json.dumps({'command': 'reload', 'data': env['reload']})
        )

    jsons = list(env.get('jsons', {}).values())
    windows = sorted(jsons, key=lambda k: ('i' not in k, k.get('i', None)))
    for v in windows:
        socket.write_message(v)

    socket.write_message(json.dumps({'command': 'layout'}))
    socket.eid = eid


def gather_envs(state):
    items = [i.replace('.json', '') for i in os.listdir(FLAGS.env_path)
             if '.json' in i]
    return sorted(list(set(items + list(state.keys()))))


class EnvHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    def get(self, eid):
        items = gather_envs(self.state)
        active = 'main' if eid not in items else eid
        self.render(
            'index.html',
            user=getpass.getuser(),
            items=[active],
            active_item=active
        )

    def post(self, args):
        sid = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )['sid']
        load_env(self.state, args, self.subs[sid])


class SaveHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources

    @staticmethod
    def wrap_func(handler, args):
        envs = args['data']
        envs = [escape_eid(eid) for eid in envs]
        ret = serialize_env(handler.state, envs)  # this drops invalid env ids
        handler.write(json.dumps(ret))

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class DataHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if 'win' in args and args['win'] is not None:
            assert args['win'] in handler.state[eid]['jsons'], \
                "Window {} doesn't exist in env {}".format(args['win'], eid)
            handler.write(json.dumps(handler.state[eid]['jsons'][args['win']]))
        else:
            handler.write(json.dumps(handler.state[eid]['jsons']))

        if args['win'] in handler.state[eid]['jsons']:
            handler.write('true')
        else:
            handler.write('false')

    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class IndexHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state

    def get(self, args, **kwargs):
        items = gather_envs(self.state)
        self.render(
            'index.html',
            user=getpass.getuser(),
            items=items,
            active_item='main'
        )


class ErrorHandler(BaseHandler):
    def get(self, text):
        error_text = text or "test error"
        raise Exception(error_text)


# function that downloads and installs javascript, css, and font dependencies:
def download_scripts(proxies=None, install_dir=None):

    print("Downloading scripts. It might take a while.")

    # location in which to download stuff:
    if install_dir is None:
        import visdom
        install_dir = os.path.dirname(visdom.__file__)

    # all files that need to be downloaded:
    b = 'https://unpkg.com/'
    bb = '%sbootstrap@3.3.7/dist/' % b
    ext_files = {
        '%sjquery@3.1.1/dist/jquery.min.js' % b: 'jquery.min.js',
        '%sbootstrap@3.3.7/dist/js/bootstrap.min.js' % b: 'bootstrap.min.js',
        '%sreact-resizable@1.4.6/css/styles.css' % b: 'react-resizable-styles.css',  # noqa
        '%sreact-grid-layout@0.14.0/css/styles.css' % b: 'react-grid-layout-styles.css',  # noqa
        '%sreact-modal@3.1.10/dist/react-modal.min.js' % b: 'react-modal.min.js',  # noqa
        '%sreact@15.6.1/dist/react.min.js' % b: 'react-react.min.js',
        '%sreact-dom@15.6.1/dist/react-dom.min.js' % b: 'react-dom.min.js',
        '%sclassnames@2.2.5' % b: 'classnames',
        '%slayout-bin-packer@1.2.2' % b: 'layout_bin_packer',
        'https://raw.githubusercontent.com/STRML/react-grid-layout/0.14.0/dist/' +  # noqa
        'react-grid-layout.min.js': 'react-grid-layout.min.js',
        'https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS-MML_SVG':  # noqa
            'mathjax-MathJax.js',
        # here is another url in case the cdn breaks down again.
        # https://raw.githubusercontent.com/plotly/plotly.js/master/dist/plotly.min.js
        'https://cdn.plot.ly/plotly-latest.min.js':
            'plotly-plotly.min.js',
        '%scss/bootstrap.min.css' % bb: 'bootstrap.min.css',
        '%sfonts/glyphicons-halflings-regular.eot' % bb:
            'glyphicons-halflings-regular.eot',
        '%sfonts/glyphicons-halflings-regular.woff2' % bb:
            'glyphicons-halflings-regular.woff2',
        '%sfonts/glyphicons-halflings-regular.woff' % bb:
            'glyphicons-halflings-regular.woff',
        '%sfonts/glyphicons-halflings-regular.ttf' % bb:
            'glyphicons-halflings-regular.ttf',
        '%sfonts/glyphicons-halflings-regular.svg#glyphicons_halflingsregular' % bb:  # noqa
            'glyphicons-halflings-regular.svg#glyphicons_halflingsregular',
    }

    # make sure all relevant folders exist:
    dir_list = [
        '%s' % install_dir,
        '%s/static' % install_dir,
        '%s/static/js' % install_dir,
        '%s/static/css' % install_dir,
        '%s/static/fonts' % install_dir,
    ]
    for directory in dir_list:
        if not os.path.exists(directory):
            os.makedirs(directory)

    # set up proxy handler:
    from six.moves.urllib import request
    from six.moves.urllib.error import HTTPError, URLError
    handler = request.ProxyHandler(proxies) if proxies is not None \
        else request.BaseHandler()
    opener = request.build_opener(handler)
    request.install_opener(opener)

    # download files one-by-one:
    for (key, val) in ext_files.items():

        # set subdirectory:
        sub_dir = 'fonts'
        if '.js' in key:
            sub_dir = 'js'
        if '.css' in key:
            sub_dir = 'css'

        # download file:
        filename = '%s/static/%s/%s' % (install_dir, sub_dir, val)
        if not os.path.exists(filename):
            req = request.Request(key,
                                  headers={'User-Agent': 'Chrome/30.0.0.0'})
            try:
                data = opener.open(req).read()
                with open(filename, 'wb') as fwrite:
                    fwrite.write(data)
            except HTTPError as exc:
                logging.error('Error {} while downloading {}'.format(
                    exc.code, key))
            except URLError as exc:
                logging.error('Error {} while downloading {}'.format(
                    exc.reason, key))


def main(print_func=None):
    print("It's Alive!")
    app = Application()
    app.listen(FLAGS.port, max_buffer_size=1024 ** 3)
    logging.info("Application Started")
    if "HOSTNAME" in os.environ:
        hostname = os.environ["HOSTNAME"]
    else:
        hostname = "localhost"
    if print_func is None:
        print("You can navigate to http://%s:%s" % (hostname, FLAGS.port))
    else:
        print_func(FLAGS.port)
    ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    download_scripts()
    main()
