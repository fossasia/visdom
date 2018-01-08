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
import json
import math
import re
import base64
import numpy as np
from PIL import Image
import base64 as b64
import numbers
from six import string_types
from six import BytesIO
import logging
import warnings

try:
    import torchfile
except BaseException:
    from . import torchfile

logging.getLogger('requests').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)


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


def _scrub_dict(d):
    if type(d) is dict:
        return dict((k, _scrub_dict(v)) for k, v in list(d.items())
                    if v is not None and _scrub_dict(v) is not None)
    else:
        return d


def _axisformat(x, opts):
    fields = ['type', 'tick', 'label', 'tickvals', 'ticklabels', 'tickmin', 'tickmax', 'tickfont']
    if any([opts.get(x + i) for i in fields]):
        return {
            'type': opts.get(x + 'type'),
            'title': opts.get(x + 'label'),
            'range': [opts.get(x + 'tickmin'), opts.get(x + 'tickmax')]
            if (opts.get(x + 'tickmin') and opts.get(x + 'tickmax')) is not None else None,
            'tickvals': opts.get(x + 'tickvals'),
            'ticktext': opts.get(x + 'ticklabels'),
            'tickwidth': opts.get(x + 'tickstep'),
            'showticklabels': opts.get(x + 'ytick'),
        }


def _opts2layout(opts, is3d=False):
    layout = {
        'showlegend': opts.get('showlegend', 'legend' in opts),
        'title': opts.get('title'),
        'xaxis': _axisformat('x', opts),
        'yaxis': _axisformat('y', opts),
        'margin': {
            'l': opts.get('marginleft', 60),
            'r': opts.get('marginright', 60),
            't': opts.get('margintop', 60),
            'b': opts.get('marginbottom', 60),
        }
    }

    if is3d:
        layout['zaxis'] = _axisformat('z', opts)

    if opts.get('stacked'):
        layout['barmode'] = 'stack' if opts.get('stacked') else 'group'

    return _scrub_dict(layout)


def _markerColorCheck(mc, X, Y, L):
    assert isndarray(mc), 'mc should be a numpy ndarray'
    assert mc.shape[0] == L or (mc.shape[0] == X.shape[0] and
            (mc.ndim == 1 or mc.ndim == 2 and mc.shape[1] == 3)), \
            ('marker colors have to be of size `%d` or `%d x 3` ' + \
            ' or `%d` or `%d x 3`, but got: %s') % \
            (X.shape[0], X.shape[1], L, L, 'x'.join(map(str,mc.shape)))

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


def pytorch_wrap(fn):
    def result(*args, **kwargs):
        args = (a.cpu().numpy() if type(a).__module__ == 'torch' else a for a in args)

        for k in kwargs:
            if type(kwargs[k]).__module__ == 'torch':
                kwargs[k] = kwargs[k].cpu().numpy()

        return fn(*args, **kwargs)
    return result


def wrap_tensor_methods(cls, wrapper):
    fns = ['_surface', 'bar', 'boxplot', 'surf', 'heatmap', 'histogram', 'svg',
           'image', 'images', 'line', 'pie', 'scatter', 'stem', 'quiver', 'contour',
           'updateTrace']
    for key in [k for k in dir(cls) if k in fns]:
        setattr(cls, key, wrapper(getattr(cls, key)))


class Visdom(object):

    def __init__(
        self,
        server='http://localhost',
        endpoint='events',
        port=8097,
        ipv6=True,
        proxy=None,
        env='main',
        send=True,
    ):
        self.server = server
        self.endpoint = endpoint
        self.port = port
        self.ipv6 = ipv6
        self.proxy = proxy
        self.env = env              # default env
        self.send = send

        try:
            import torch  # noqa F401: we do use torch, just weirdly
            wrap_tensor_methods(self, pytorch_wrap)
        except ImportError:
            pass

    # Utils
    def _send(self, msg, endpoint='events', quiet=False):
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
                "{0}:{1}/{2}".format(self.server, self.port, endpoint),
                data=json.dumps(msg),
            )
            return r.text
        except BaseException:
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

    def win_exists(self, win, env=None):
        """
        This function returns a bool indicating whether
        or not a window exists on the server already.
        Returns None if something went wrong
        """
        e = self._win_exists_wrap(win, env)
        if e == 'true':
            return True
        elif e == 'false':
            return False
        else:
            return None

    def check_connection(self):
        """
        This function returns a bool indicating whether or
        not the server is connected.
        """
        return self.win_exists('') is not None

    # Content

    def text(self, text, win=None, env=None, opts=None, append=False):
        """
        This function prints text in a box. It takes as input an `text` string.
        No specific `opts` are currently supported.
        """
        opts = {} if opts is None else opts
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

    def svg(self, svgstr=None, svgfile=None, win=None, env=None, opts=None):
        """
        This function draws an SVG object. It takes as input an SVG string or the
        name of an SVG file. The function does not support any plot-specific
        `options`.
        """
        opts = {} if opts is None else opts
        _assert_opts(opts)

        if svgfile is not None:
            svgstr = loadfile(svgfile)

        assert svgstr is not None, 'should specify SVG string or filename'
        svg = re.search('<svg .+</svg>', svgstr, re.DOTALL)
        assert svg is not None, 'could not parse SVG string'
        return self.text(text=svg.group(0), win=win, env=env, opts=opts)

    def image(self, img, win=None, env=None, opts=None):
        """
        This function draws an img. It takes as input an `CxHxW` or `HxW` tensor
        `img` that contains the image. The array values can be float in [0,1] or
        uint8 in [0, 255].
        """
        opts = {} if opts is None else opts
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
        height, width = int(tensor.shape[2] + 2 * padding), int(tensor.shape[3] + 2 * padding)

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

    def video(self, tensor=None, videofile=None, win=None, env=None, opts=None):
        """
        This function plays a video. It takes as input the filename of the video
        or a `LxHxWxC` tensor containing all the frames of the video. The function
        does not support any plot-specific `options`.
        """
        opts = {} if opts is None else opts
        opts['fps'] = opts.get('fps', 25)
        _assert_opts(opts)
        assert tensor is not None or videofile is not None, \
            'should specify video tensor or file'

        if tensor is not None:
            import cv2
            import tempfile
            assert tensor.ndim == 4, 'video should be in 4D tensor'
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
                (tensor.shape[1], tensor.shape[2])
            )
            assert writer.isOpened(), 'video writer could not be opened'
            for i in range(tensor.shape[0]):
                writer.write(tensor[i, :, :, :])
            writer.release()
            writer = None

        extension = videofile.split(".")[-1].lower()
        mimetypes = dict(mp4='mp4', ogv='ogg', avi='avi', webm='webm')
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

    def updateTrace(self, X, Y, win, env=None, name=None,
                    append=True, opts=None):
        """
        This function allows updating of the data of a line or scatter plot.

        It is up to the user to specify `name` of an existing trace if they want
        to add to it, and a new `name` if they want to add a trace to the plot.
        By default, if no legend is specified, the `name` is the index of the
        line in the legend.

        If no `name` is specified, all traces should be updated.
        Update data that is all NaN is ignored (can be used for masking update).

        The `append` parameter determines if the update data should be appended
        to or replaces existing data.

        There are less options because they are assumed to inherited from the
        specified plot.
        """
        warnings.warn("updateTrace is going to be deprecated in the next "
                      "version of `visdom`. Please to use `scatter(.., "
                      "update='append',name=<traceName>)` or `line(.., "
                      "update='append',name=<traceName>)` as required.",
                      PendingDeprecationWarning)
        assert win is not None

        assert Y.shape == X.shape, 'Y should be same size as X'
        if X.ndim > 2:
            X = np.squeeze(X)
            Y = np.squeeze(Y)
        assert X.ndim == 1 or X.ndim == 2, 'Updated X should be 1 or 2 dim'

        if name:
            assert len(name) >= 0, 'name of trace should be nonempty string'
            assert X.ndim == 1, 'updating by name expects 1-dim data'

        if opts is not None and opts.get('markercolor') is not None:
            K = int(Y.max())
            opts['markercolor'] = _markerColorCheck(
                opts['markercolor'], X, Y, K)

        data = {'x': X.transpose().tolist(), 'y': Y.transpose().tolist()}
        if X.ndim == 1:
            data['x'] = [data['x']]
            data['y'] = [data['y']]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'name': name,
            'append': append,
            'opts': opts,
        }, endpoint='update')

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

    def scatter(self, X, Y=None, win=None, env=None, opts=None, update=None,
                name=None):
        """
        This function draws a 2D or 3D scatter plot. It takes in an `Nx2` or
        `Nx3` tensor `X` that specifies the locations of the `N` points in the
        scatter plot. An optional `N` tensor `Y` containing discrete labels that
        range between `1` and `K` can be specified as well -- the labels will be
        reflected in the colors of the markers.

        `update` can be used to efficiently update the data of an existing plot.
        Use 'append' to append data, 'replace' to use new data. If updating a
        single trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).

        The following `opts` are supported:

        - `opts.colormap`    : colormap (`string`; default = `'Viridis'`)
        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number`; default = `'10'`)
        - `opts.markercolor` : marker color (`np.array`; default = `None`)
        - `opts.legend`      : `table` containing legend names
        """
        if update is not None:
            assert win is not None

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
        opts['colormap'] = opts.get('colormap', 'Viridis')
        opts['mode'] = opts.get('mode', 'markers')
        opts['markersymbol'] = opts.get('markersymbol', 'dot')
        opts['markersize'] = opts.get('markersize', 10)

        if opts.get('markercolor') is not None:
            opts['markercolor'] = _markerColorCheck(
                opts['markercolor'], X, Y, K)

        _assert_opts(opts)

        if opts.get('legend'):
            assert type(opts['legend']) == list and len(opts['legend']) == K

        data = []
        for k in range(1, K + 1):
            ind = np.equal(Y, k)
            if ind.any():
                mc = opts.get('markercolor')
                _data = {
                    'x': nan2none(X.take(0, 1)[ind].tolist()),
                    'y': nan2none(X.take(1, 1)[ind].tolist()),
                    'name': opts.get('legend')[k - 1] if 'legend' in opts
                    else str(k),
                    'type': 'scatter3d' if is3d else 'scatter',
                    'mode': opts.get('mode'),
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

                data.append(_scrub_dict(_data))

        if opts:
            for marker_prop in ['markercolor']:
                if marker_prop in opts:
                    del opts[marker_prop]

        data_to_send = {
            'data': data,
            'win': win,
            'eid': env,
            'layout': _opts2layout(opts, is3d),
            'opts': opts,
        }
        endpoint = 'events'
        if update:
            data_to_send['name'] = name
            data_to_send['append'] = update == 'append'
            endpoint = 'update'

        return self._send(data_to_send, endpoint=endpoint)

    def line(self, Y, X=None, win=None, env=None, opts=None, update=None,
             name=None):
        """
        This function draws a line plot. It takes in an `N` or `NxM` tensor
        `Y` that specifies the values of the `M` lines (that connect `N` points)
        to plot. It also takes an optional `X` tensor that specifies the
        corresponding x-axis values; `X` can be an `N` tensor (in which case all
        lines will share the same x-axis values) or have the same size as `Y`.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data. If updating a
        single trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).

        The following `opts` are supported:

        - `opts.fillarea`    : fill area below line (`boolean`)
        - `opts.colormap`    : colormap (`string`; default = `'Viridis'`)
        - `opts.markers`     : show markers (`boolean`; default = `false`)
        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number`; default = `'10'`)
        - `opts.legend`      : `table` containing legend names

        If `update` is specified, the figure will be updated without
        creating a new plot -- this can be used for efficient updating.
        """
        if update is not None:
            assert X is not None, 'must specify x-values for line update'
        assert Y.ndim == 1 or Y.ndim == 2, 'Y should have 1 or 2 dim'

        if X is not None:
            assert X.ndim == 1 or X.ndim == 2, 'X should have 1 or 2 dim'
        else:
            X = np.linspace(0, 1, Y.shape[0])

        if Y.ndim == 2 and X.ndim == 1:
            X = np.tile(X, (Y.shape[1], 1)).transpose()

        assert X.shape == Y.shape, 'X and Y should be the same shape'

        opts = {} if opts is None else opts
        opts['markers'] = opts.get('markers', False)
        opts['fillarea'] = opts.get('fillarea', False)
        opts['mode'] = 'lines+markers' if opts.get('markers') else 'lines'

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
        opts['xmin'] = opts.get('xmin', X.min())
        opts['xmax'] = opts.get('xmax', X.max())
        opts['colormap'] = opts.get('colormap', 'Viridis')
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

    def quiver(self, X, Y, gridX=None, gridY=None,
                            win=None, env=None, opts=None):
        """
        This function draws a quiver plot in which the direction and length of the
        arrows is determined by the `NxM` tensors `X` and `Y`. Two optional `NxM`
        tensors `gridX` and `gridY` can be provided that specify the offsets of
        the arrows; by default, the arrows will be done on a regular grid.

        The following `options` are supported:

        - `options.normalize`:  length of longest arrows (`number`)
        - `options.arrowheads`: show arrow heads (`boolean`; default = `true`)
        """

        # assertions:
        assert X.ndim == 2, 'X should be two-dimensional'
        assert Y.ndim == 2, 'Y should be two-dimensional'
        assert Y.shape == X.shape, 'X and Y should have the same size'

        # make sure we have a grid:
        N, M = X.shape[0], X.shape[1]
        if gridX is None:
            gridX = np.broadcast_to(np.expand_dims(np.arange(0, N), axis=1), (N, M))
        if gridY is None:
            gridY = np.broadcast_to(np.expand_dims(np.arange(0, M), axis=0), (N, M))
        assert gridX.shape == X.shape, 'X and gridX should have the same size'
        assert gridY.shape == Y.shape, 'Y and gridY should have the same size'

        # default options:
        opts = {} if opts is None else opts
        opts['mode'] = 'lines'
        opts['arrowheads'] = opts.get('arrowheads', True)
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
        _assert_opts(opts)

        return self.scatter(X=data, Y=labels, opts=opts, win=win, env=env)

    def pie(self, X, win=None, env=None, opts=None):
        """
        This function draws a pie chart based on the `N` tensor `X`.

        The following `options` are supported:

        - `options.legend`: `table` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1, 'X should be one-dimensional'
        assert np.all(np.greater_equal(X, 0)), \
            'X cannot contain negative values'

        opts = {} if opts is None else opts
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

    def mesh(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a mesh plot from a set of vertices defined in an
        `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or
        `Mx3` matrix `Y`.

        The following `options` are supported:

        - `options.color`: color (`string`)
        - `options.opacity`: opacity of polygons (`number` between 0 and 1)
        """
        opts = {} if opts is None else opts
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
