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
import os
import inspect
import time
import getpass
import argparse
import copy

from os.path import expanduser
from zmq.eventloop import ioloop
ioloop.install()  # Needs to happen before any tornado imports!

import tornado.ioloop
import tornado.web
import tornado.websocket

logging.getLogger().setLevel(logging.INFO)

parser = argparse.ArgumentParser(description='Start the visdom server.')
parser.add_argument('-port', metavar='port', type=int, default=8097,
                    help='port to run the server on.')
parser.add_argument('-env_path', metavar='env_path', type=str,
                    default='%s/.visdom/' % expanduser("~"),
                    help='path to serialized session to reload (end with /).')
FLAGS = parser.parse_args()


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
    cwd = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    return os.path.join(cwd, filename)


tornado_settings = {
    "autoescape": None,
    "debug": "/dbg/" in __file__,
    "static_path": get_path('static'),
    "template_path": get_path('static'),
    "compiled_template_cache": False
}


def serialize_env(state, eids):
    l = [i for i in eids if i in state]
    for i in l:
        p = '%s/%s.json' % (FLAGS.env_path, i)
        open(p, 'w').write(json.dumps(state[i]))
    return l


def serialize_all(state):
    serialize_env(state, state.keys())


class Application(tornado.web.Application):
    def __init__(self):
        state = {}
        subs = {}

        # reload state
        ensure_dir_exists(FLAGS.env_path)
        l = [i for i in os.listdir(FLAGS.env_path) if '.json' in i]

        for i in l:
            p = os.path.join(FLAGS.env_path, i)
            f = json.loads(open(p, 'r').read())
            eid = i.replace('.json', '')
            state[eid] = {'jsons': f['jsons'], 'reload': f['reload']}

        if 'main' not in state and 'main.json' not in l:
            state['main'] = {'jsons': {}, 'reload': {}}
            serialize_env(state, ['main'])

        handlers = [
            (r"/events", PostHandler, dict(state=state, subs=subs)),
            (r"/update", UpdateHandler, dict(state=state, subs=subs)),
            (r"/close", CloseHandler, dict(state=state, subs=subs)),
            (r"/socket", SocketHandler, dict(state=state, subs=subs)),
            (r"/env/(.*)", EnvHandler, dict(state=state, subs=subs)),
            (r"/save", SaveHandler, dict(state=state, subs=subs)),
            (r"/error/(.*)", ErrorHandler),
            (r"/(.*)", IndexHandler, dict(state=state)),
        ]
        super(Application, self).__init__(handlers, **tornado_settings)


class SocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

    def check_origin(self, origin):
        return True

    def open(self):
        self.sid = str(hex(int(time.time() * 10000000))[2:])
        if self not in self.subs.values():
            self.eid = 'main'
            self.subs[self.sid] = self
        print('Opened new socket from ip:', self.request.remote_ip)

        self.write_message(
            json.dumps({'command': 'register', 'data': self.sid}))

    def on_message(self, message):
        print('from web client: ', message)
        msg = json.loads(message)
        cmd = msg.get('cmd')
        if cmd == 'close':
            if 'data' in msg and 'eid' in msg:
                print('closing pane ', msg['data'])
                self.state[msg['eid']]['jsons'].pop(msg['data'], None)

        elif cmd == 'save':
            # save localStorage pane metadata
            if 'data' in msg and 'eid' in msg:
                self.state[msg['eid']] = copy.deepcopy(self.state[msg['prev_eid']])
                self.state[msg['eid']]['reload'] = msg['data']
                self.eid = msg['eid']
                serialize_env(self.state, [self.eid])

    def on_close(self):
        if self in self.subs.values():
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
                params = dict(
                    error=exc_info[1],
                    trace_info=traceback.format_exception(*exc_info),
                    request=self.request.__dict__
                )

                self.render("error.html", **params)
                logging.error("rendering complete")
            except Exception as e:
                logging.error(e)


def pane(args):
    """ Build a pane dict structure for sending to client """

    if args.get('win') is None:
        uid = 'pane_' + get_rand_id()
    else:
        uid = args['win']

    return {
        'command': 'pane',
        'id': uid,
        'title': '' if args.get('title') is None else args['title'],
        'contentID': get_rand_id(),   # to detected updated panes

    }


def broadcast(self, msg, eid):
    for s in self.subs:
        if self.subs[s].eid == eid:
            self.subs[s].write_message(msg)


def register_pane(self, p, eid):
    # in case env doesn't exist
    self.state[eid] = self.state.get(eid, {'jsons': {}, 'reload': {}})
    env = self.state[eid]['jsons']

    if p['id'] in env:
        p['i'] = env[p['id']]['i']
    else:
        p['i'] = len(env)

    env[p['id']] = p

    broadcast(self, p, eid)
    self.write(p['id'])


class PostHandler(BaseHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

    def post(self):
        args = json.loads(self.request.body)

        ptype = args['data'][0]['type']
        p = pane(args)
        eid = 'main' if args.get('eid') is None else args.get('eid')

        if ptype in ['image', 'text']:
            p.update(dict(content=args['data'][0]['content'], type=ptype))
        else:
            p['content'] = dict(data=args['data'], layout=args['layout'])
            p['type'] = 'plot'

        register_pane(self, p, eid)


class UpdateHandler(BaseHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

    def update(self, p, args):
        pdata = p['content']['data']

        new_data = args['data']
        name = args.get('name')
        append = args.get('append')

        idxs = range(len(pdata))

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
            if all([math.isnan(i) or i is None for i in new_data['x'][n]]):
                continue

            pdata[idx]['x'] = (pdata[idx]['x'] + new_data['x'][n]) if append \
                else new_data['x'][n]
            pdata[idx]['y'] = (pdata[idx]['y'] + new_data['y'][n]) if append \
                else new_data['y'][n]

        return p

    def post(self):
        args = json.loads(self.request.body)
        eid = 'main' if args.get('eid') is None else args.get('eid')

        if args['win'] not in self.state[eid]['jsons']:
            self.write('win does not exist')
            return

        p = self.state[eid]['jsons'][args['win']]

        if not p['content']['data'][0]['type'] == 'scatter':
            self.write('win is not scatter')
            return

        p = self.update(p, args)

        p['contentID'] = get_rand_id()
        broadcast(self, p, eid)
        self.write(p['id'])


class CloseHandler(BaseHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

    def post(self):
        args = json.loads(self.request.body)

        eid = 'main' if args.get('eid') is None else args.get('eid')
        win = args.get('win')

        keys = list(self.state[eid]['jsons'].keys()) if win is None else [win]
        for win in keys:
            self.state[eid]['jsons'].pop(win, None)
            broadcast(
                self, json.dumps({'command': 'close', 'data': win}), eid
            )


def load_env(state, eid, socket):
    """ load an environment to a client by socket """

    env = {}
    if eid in state:
        env = state.get(eid)
    else:
        p = os.path.join(FLAGS.env_path, eid.strip(), '.json')
        if os.path.exists(p):
            env = json.loads(open(p, 'r').read())
            state[eid] = env

    if 'reload' in env:
        socket.write_message(
            json.dumps({'command': 'reload', 'data': env['reload']})
        )

    jsons = env.get('jsons', {}).values()
    panes = sorted(jsons, key=lambda k: ('i' not in k, k.get('i', None)))
    for v in panes:
        socket.write_message(v)

    socket.write_message(json.dumps({'command': 'layout'}))
    socket.eid = eid


def gather_envs(state):
    items = [i.replace('.json', '') for i in os.listdir(FLAGS.env_path)
                if '.json' in i]
    return sorted(list(set(items + state.keys())))


class EnvHandler(BaseHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

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
        sid = json.loads(self.request.body)['sid']
        load_env(self.state, args, self.subs[sid])


class SaveHandler(BaseHandler):
    def initialize(self, state, subs):
        self.state = state
        self.subs = subs

    def post(self):
        envs = json.loads(self.request.body)['data']
        ret = serialize_env(self.state, envs)  # this ignores invalid env ids
        self.write(json.dumps(ret))


class IndexHandler(BaseHandler):
    def initialize(self, state):
        self.state = state

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


def main():
    print("It's Alive!")
    app = Application()
    app.listen(FLAGS.port, max_buffer_size=1024 ** 3)
    ioloop.IOLoop.instance().start()
    logging.info("Application Started")


if __name__ == "__main__":
    main()
