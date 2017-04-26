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
                                        if v and _scrub_dict(v))
    else:
        return d


def _axisformat(x, options):
    fields = ['type', 'tick', 'label', 'tickmin', 'tickmax']
    if any([x + i for i in fields]):
        return {
            'type': options.get(x + 'type'),
            'title': options.get(x + 'label'),
            'range': [options.get(x + 'tickmin'), options.get(x + 'tickmax')]
            if (options.get(x + 'tickmin') and options.get(x + 'tickmax')) else None,
            'tickwidth': options.get(x + 'tickstep'),
            'showticklabels': options.get(x + 'ytick'),
        }


def _options2layout(options, is3d=False):
    layout = {
        'width': options.get('width'),
        'height': options.get('height'),
        'showlegend': options.get('legend', False),
        'title': options.get('title'),
        'xaxis': _axisformat('x', options),
        'yaxis': _axisformat('y', options),
        'margin': {
            'l': options.get('marginleft', 60),
            'r': options.get('marginright', 60),
            't': options.get('margintop', 60),
            'b': options.get('marginbottom', 60),
        }
    }

    if is3d:
        layout['zaxis'] = _axisformat('z', options)

    if options.get('stacked'):
        layout['barmode'] = 'stack' if options.get('stacked') else 'group'

    return _scrub_dict(layout)


def _markerColorCheck(mc, X, Y, L):
    assert isndarray(mc), 'mc should be a numpy ndarray'
    assert mc.shape[0] == L or (mc.shape[0] == X.shape[0] and
            (mc.ndim == 1 or mc.ndim == 2 and mc.shape[1] == 3)), \
            'marker colors have to be of size `%d` or `%d x 3` ' + \
            ' or `%d` or `%d x 3`, but got: %s' % \
            (X.shape[0], X.shape[1], L, L, 'x'.join(mc.shape))

    assert (mc >= 0).all(), 'marker colors have to be >= 0'
    assert (mc <= 255).all(), 'marker colors have to be <= 255'
    assert (mc == np.floor(mc)).all(), 'marker colors are assumed to be ints'

    mc = np.uint8(mc)

    if mc.ndim == 1:
        markercolor = mc.tolist()
    else:
        markercolor = ['#%x%x%x' % (i[0], i[1], i[2]) for i in mc]

    if mc.shape[0] != X.shape[0]:
        markercolor = [markercolor[Y[i] - 1] for i in range(Y.shape[0])]

    ret = {}
    for k, v in enumerate(markercolor):
        ret[Y[k]] = ret.get(Y[k], []) + [v]

    return ret


def _assert_options(options):
    if options.get('color'):
        assert isstr(options.get('color')), 'color should be a string'

    if options.get('colormap'):
        assert isstr(options.get('colormap')), \
            'colormap should be string'

    if options.get('mode'):
        assert isstr(options.get('mode')), 'mode should be a string'

    if options.get('markersymbol'):
        assert isstr(options.get('markersymbol')), \
            'marker symbol should be string'

    if options.get('markersize'):
        assert isnum(options.get('markersize')) \
            and options.get('markersize') > 0, \
            'marker size should be a positive number'

    if options.get('columnnames'):
        assert isinstance(options.get('columnnames'), list), \
            'columnnames should be a table with column names'

    if options.get('rownames'):
        assert isinstance(options.get('rownames'), list), \
            'rownames should be a table with row names'

    if options.get('jpgquality'):
        assert isnum(options.get('jpgquality')), \
            'JPG quality should be a number'
        assert options.get('jpgquality') > 0 and options.get('jpgquality') <= 100, \
            'JPG quality should be number between 0 and 100'

    if options.get('opacity'):
        assert isnum(options.get('opacity')), 'opacity should be a number'
        assert 0 <= options.get('opacity') <= 1, \
            'opacity should be a number between 0 and 1'

def pytorch_wrap(fn):
    """Convert PyTorch tensor arguments to Numpy arrays"""

    def result(*args, **kwargs):
        args = (a.cpu().numpy() if type(a).__module__ == 'torch' else a
                for a in args)

        for k in kwargs:
            if type(kwargs[k]).__module__ == 'torch':
                kwargs[k] = kwargs[k].cpu().numpy()

        return fn(*args, **kwargs)
    return result

def opts_wrap(fn):
    """Deprecate `opts` for `options` without breaking backwards compatibility"""

    def result(*args, **kwargs):
        if 'opts' in kwargs:
            # print("Warning: opts is deprecated, use options")
            kwargs['options'] = kwargs['opts']
            del kwargs['opts']

        return fn(*args, **kwargs)
    return result

tensor_methods = ['_surface', 'bar', 'boxplot', 'surf', 'heatmap', 'histogram', 'svg',
    'image', 'line', 'pie', 'scatter', 'stem', 'contour', 'updateTrace']

opts_methods = ['text', 'svg', 'image', 'images', 'video', 'updateTrace', 'scatter',
    'line', 'heatmap', 'bar', 'histogram', 'boxplot', '_surface', 'surf',
    'contour', 'stem', 'pie', 'mesh']

def wrap_methods(cls, method_names, wrapper):
    """Replace given class methods with a wrapped version"""

    for key in [k for k in dir(cls) if k in method_names]:
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
    ):
        self.server = server
        self.endpoint = endpoint
        self.port = port
        self.ipv6 = ipv6
        self.proxy = proxy
        self.env = env              # default env

        wrap_methods(self, opts_methods, opts_wrap)

        try:
            import torch
            wrap_methods(self, tensor_methods, pytorch_wrap)
        except ImportError:
            pass

    # Utils
    def _send(self, msg, endpoint='events'):
        """
        This function sends specified JSON request to the Tornado server. This
        function should generally not be called by the user, unless you want to
        build the required JSON yourself. `endpoint` specifies the destination
        Tornado server endpoint for the request.
        """
        if msg.get('eid', None) is None:
            msg['eid'] = self.env

        try:
            r = requests.post(
                "{0}:{1}/{2}".format(self.server, self.port, endpoint),
                data=json.dumps(msg),
            )
            return r.text
        except BaseException:
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

    # Content

    def text(self, text, win=None, env=None, options=None):
        """
        This function prints text in a box. It takes as input an `text` string.
        No specific `options` are currently supported.
        """
        options = {} if options is None else options
        _assert_options(options)
        data = [{'content': text, 'type': 'text'}]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'title': options.get('title'),
        })

    def svg(self, svgstr=None, svgfile=None, win=None, env=None, options=None):
        """
        This function draws an SVG object. It takes as input an SVG string or the
        name of an SVG file. The function does not support any plot-specific
        `options`.
        """
        options = {} if options is None else options
        _assert_options(options)

        if svgfile is not None:
            svgstr = loadfile(svgfile)

        assert svgstr is not None, 'should specify SVG string or filename'
        svg = re.search('<svg .+</svg>', svgstr, re.DOTALL)
        assert svg is not None, 'could not parse SVG string'
        return self.text(text=svg.group(0), win=win, env=env, options=options)

    def image(self, img, win=None, env=None, options=None):
        """
        This function draws an img. It takes as input an `CxHxW` tensor `img`
        that contains the image. The array values can be float in [0,1] or uint8
        in [0, 255].
        """
        options = {} if options is None else options
        options['jpgquality'] = options.get('jpgquality', 75)
        _assert_options(options)

        nchannels = img.shape[0] if img.ndim == 3 else 1
        if nchannels == 1:
            img = img[np.newaxis, :, :].repeat(3, axis=0)

        if 'float' in str(img.dtype):
            if img.max() <= 1:
                img = img * 255.
            img = np.uint8(img)

        img = np.transpose(img, (1, 2, 0))
        im = Image.fromarray(img)
        buf = BytesIO()
        im.save(buf, format='JPEG', quality=options['jpgquality'])
        b64encoded = b64.b64encode(buf.getvalue()).decode('utf-8')

        data = [{
            'content': {
                'src': 'data:image/jpg;base64,' + b64encoded,
                'caption': options.get('caption'),
                'size': options.get('size', list(img.shape)),
            },
            'type': 'image',
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'title': options.get('title'),
        })

    def images(self, tensor, nrow=8, padding=2,
               win=None, env=None, options=None):
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
            return self.image(tensor, win, env, options)
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

        return self.image(grid, win, env, options)

    def video(self, tensor=None, videofile=None, win=None, env=None, options=None):
        """
        This function plays a video. It takes as input the filename of the video
        or a `LxCxHxW` tensor containing all the frames of the video. The function
        does not support any plot-specific `options`.
        """
        options = {} if options is None else options
        _assert_options(options)
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
                25,
                (tensor.shape[1], tensor.shape[2])
            )
            assert writer.isOpened(), 'video writer could not be opened'
            for i in range(tensor.shape[0]):
                writer.write(tensor[i, :, :, :])
            writer.release()
            writer = None

        extension = videofile[-3:].lower()
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
        return self.text(text=videodata, win=win, env=env, options=options)

    def updateTrace(self, X, Y, win, env=None, name=None,
                    append=True, options=None):
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
        assert win is not None

        assert Y.shape == X.shape, 'Y should be same size as X'
        if X.ndim > 2:
            X = np.squeeze(X)
            Y = np.squeeze(Y)
        assert X.ndim == 1 or X.ndim == 2, 'Updated X should be 1 or 2 dim'

        if name:
            assert len(name) >= 0, 'name of trace should be nonempty string'
            assert X.ndim == 1, 'updating by name expects 1-dim data'

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
        }, endpoint='update')

    def scatter(self, X, Y=None, win=None, env=None, options=None, update=None):
        """
        This function draws a 2D or 3D scatter plot. It takes in an `Nx2` or
        `Nx3` tensor `X` that specifies the locations of the `N` points in the
        scatter plot. An optional `N` tensor `Y` containing discrete labels that
        range between `1` and `K` can be specified as well -- the labels will be
        reflected in the colors of the markers.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data.
        Update data that is all NaN is ignored (can be used for masking update).

        The following `options` are supported:

        - `options.colormap`    : colormap (`string`; default = `'Viridis'`)
        - `options.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `options.markersize`  : marker size (`number`; default = `'10'`)
        - `options.markercolor` : marker color (`np.array`; default = `None`)
        - `options.legend`      : `table` containing legend names
        """
        if update is not None:
            return self.updateTrace(X=X, Y=Y, win=win, env=env,
                                    append=update == 'append', options=options)

        assert X.ndim == 2, 'X should have two dims'
        assert X.shape[1] == 2 or X.shape[1] == 3, 'X should have 2 or 3 cols'

        if Y is not None:
            Y = np.squeeze(Y)
            assert Y.ndim == 1, 'Y should be one-dimensional'
            assert X.shape[0] == Y.shape[0], 'sizes of X and Y should match'
        else:
            Y = np.ones(X.shape[0])

        assert np.equal(np.mod(Y, 1), 0).all(), 'labels should be integers'
        assert Y.min() == 1, 'labels are assumed to be between 1 and K'

        K = int(Y.max())
        is3d = X.shape[1] == 3

        options = {} if options is None else options
        options['colormap'] = options.get('colormap', 'Viridis')
        options['mode'] = options.get('mode', 'markers')
        options['markersymbol'] = options.get('markersymbol', 'dot')
        options['markersize'] = options.get('markersize', 10)

        if options.get('markercolor') is not None:
            options['markercolor'] = _markerColorCheck(
                options['markercolor'], X, Y, K)

        _assert_options(options)

        if options.get('legend'):
            assert type(options['legend']) == list and len(options['legend']) == K

        data = []
        for k in range(1, K + 1):
            ind = np.equal(Y, k)
            if ind.any():
                mc = options.get('markercolor')
                _data = {
                    'x': nan2none(X.take(0, 1)[ind].tolist()),
                    'y': nan2none(X.take(1, 1)[ind].tolist()),
                    'name': options.get('legend') and
                    options.get('legend')[k - 1] or str(k),
                    'type': 'scatter3d' if is3d else 'scatter',
                    'mode': options.get('mode'),
                    'marker': {
                        'size': options.get('markersize'),
                        'symbol': options.get('markersymbol'),
                        'color': mc[k] if mc is not None else None,
                        'line': {
                            'color': '#000000',
                            'width': 0.5
                        }
                    }
                }
                if options.get('fillarea'):
                    _data['fill'] = 'tonexty'

                if is3d:
                    _data['z'] = X.take(2, 1)[ind].tolist()

                data.append(_scrub_dict(_data))

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options, is3d),
        })

    def line(self, Y, X=None, win=None, env=None, options=None, update=None):
        """
        This function draws a line plot. It takes in an `N` or `NxM` tensor
        `Y` that specifies the values of the `M` lines (that connect `N` points)
        to plot. It also takes an optional `X` tensor that specifies the
        corresponding x-axis values; `X` can be an `N` tensor (in which case all
        lines will share the same x-axis values) or have the same size as `Y`.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data.
        Update data that is all NaN is ignored (can be used for masking update).

        The following `options` are supported:

        - `options.fillarea`    : fill area below line (`boolean`)
        - `options.colormap`    : colormap (`string`; default = `'Viridis'`)
        - `options.markers`     : show markers (`boolean`; default = `false`)
        - `options.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `options.markersize`  : marker size (`number`; default = `'10'`)
        - `options.legend`      : `table` containing legend names

        If `update` is specified, the figure will be updated without
        creating a new plot -- this can be used for efficient updating.
        """
        if update is not None:
            assert X is not None, 'must specify x-values for line update'
            return self.updateTrace(X=X, Y=Y, win=win, env=env,
                                    append=update == 'append', options=options)
        assert Y.ndim == 1 or Y.ndim == 2, 'Y should have 1 or 2 dim'

        if X is not None:
            assert X.ndim == 1 or X.ndim == 2, 'X should have 1 or 2 dim'
        else:
            X = np.linspace(0, 1, Y.shape[0])

        if Y.ndim == 2 and X.ndim == 1:
            X = np.tile(X, (Y.shape[1], 1)).transpose()

        assert X.shape == Y.shape, 'X and Y should be the same shape'

        options = {} if options is None else options
        options['markers'] = options.get('markers', False)
        options['fillarea'] = options.get('fillarea', False)
        options['mode'] = 'lines+markers' if options.get('markers') else 'lines'

        _assert_options(options)

        if Y.ndim == 1:
            linedata = np.column_stack((X, Y))
        else:
            linedata = np.column_stack((X.ravel(order='F'), Y.ravel(order='F')))

        labels = None
        if Y.ndim == 2:
            labels = np.arange(1, Y.shape[1] + 1)
            labels = np.tile(labels, (Y.shape[0], 1)).ravel(order='F')

        return self.scatter(X=linedata, Y=labels, options=options, win=win, env=env)

    def heatmap(self, X, win=None, env=None, options=None):
        """
        This function draws a heatmap. It takes as input an `NxM` tensor `X`
        that specifies the value at each location in the heatmap.

        The following `options` are supported:

        - `options.colormap`: colormap (`string`; default = `'Viridis'`)
        - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
        - `options.columnnames`: `table` containing x-axis labels
        - `options.rownames`: `table` containing y-axis labels
        """

        assert X.ndim == 2, 'data should be two-dimensional'
        options = {} if options is None else options
        options['xmin'] = options.get('xmin', np.asscalar(X.min()))
        options['xmax'] = options.get('xmax', np.asscalar(X.max()))
        options['colormap'] = options.get('colormap', 'Viridis')
        _assert_options(options)

        if options.get('columnnames') is not None:
            assert len(options['columnnames']) == X.shape[1], \
                'number of column names should match number of columns in X'

        if options.get('rownames') is not None:
            assert len(options['rownames']) == X.shape[0], \
                'number of row names should match number of rows in X'

        data = [{
            'z': X.tolist(),
            'x': options.get('columnnames'),
            'y': options.get('rownames'),
            'zmin': options.get('xmin'),
            'zmax': options.get('xmax'),
            'type': 'heatmap',
            'colorscale': options.get('colormap'),
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options)
        })

    def bar(self, X, Y=None, win=None, env=None, options=None):
        """
        This function draws a regular, stacked, or grouped bar plot. It takes as
        input an `N` or `NxM` tensor `X` that specifies the height of each
        bar. If `X` contains `M` columns, the values corresponding to each row
        are either stacked or grouped (dependending on how `options.stacked` is
        set). In addition to `X`, an (optional) `N` tensor `Y` can be specified
        that contains the corresponding x-axis values.

        The following plot-specific `options` are currently supported:

        - `options.rownames`: `table` containing x-axis labels
        - `options.stacked` : stack multiple columns in `X`
        - `options.legend`  : `table` containing legend labels
        """
        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, 'X should be one or two-dimensional'
        if X.ndim == 1:
            X = X[:, None]
        if Y is not None:
            Y = np.squeeze(Y)
            assert Y.ndim == 1, 'Y should be one-dimensional'
            assert len(X) == len(Y), 'sizes of X and Y should match'
        else:
            Y = np.arange(1, len(X) + 1)

        options = {} if options is None else options
        options['stacked'] = options.get('stacked', False)

        _assert_options(options)

        if options.get('rownames') is not None:
            assert len(options['rownames']) == X.shape[0], \
                'number of row names should match number of rows in X'

        if options.get('legend') is not None:
            assert len(options['legend']) == X.shape[1], \
                'number of legened labels must match number of columns in X'

        data = []
        for k in range(X.shape[1]):
            _data = {
                'y': X.take(k, 1).tolist(),
                'x': options.get('rownames', Y.tolist()),
                'type': 'bar',
            }
            if options.get('legend'):
                _data['name'] = options['legend'][k]
            data.append(_data)

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options)
        })

    def histogram(self, X, win=None, env=None, options=None):
        """
        This function draws a histogram of the specified data. It takes as input
        an `N` tensor `X` that specifies the data of which to construct the
        histogram.

        The following plot-specific `options` are currently supported:

        - `options.numbins`: number of bins (`number`; default = 30)
        """

        X = np.squeeze(X)
        assert X.ndim == 1, 'X should be one-dimensional'

        options = {} if options is None else options
        options['numbins'] = options.get('numbins', min(30, len(X)))
        _assert_options(options)

        minx, maxx = X.min(), X.max()
        bins = np.histogram(X, bins=options['numbins'], range=(minx, maxx))[0]
        linrange = np.linspace(minx, maxx, options['numbins'])

        return self.bar(
            X=bins,
            Y=linrange,
            options=options,
            win=win,
            env=env
        )

    def boxplot(self, X, win=None, env=None, options=None):
        """
        This function draws boxplots of the specified data. It takes as input
        an `N` or an `NxM` tensor `X` that specifies the `N` data values of
        which to construct the `M` boxplots.

        The following plot-specific `options` are currently supported:
        - `options.legend`: labels for each of the columns in `X`
        """

        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, 'X should be one or two-dimensional'
        if X.ndim == 1:
            X = X[:, None]

        options = {} if options is None else options
        _assert_options(options)

        if options.get('legend') is not None:
            assert len(options['legend']) == X.shape[1], \
                'number of legened labels must match number of columns'

        data = []
        for k in range(X.shape[1]):
            _data = {
                'y': X.take(k, 1).tolist(),
                'type': 'box',
            }
            if options.get('legend'):
                _data['name'] = options['legend'][k]
            else:
                _data['name'] = 'column ' + str(k)

            data.append(_data)

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options)
        })

    def _surface(self, X, stype, win=None, env=None, options=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        `stype` is 'contour' (2D) or 'surf' (3D).

        The following `options` are supported:

        - `options.colormap`: colormap (`string`; default = `'Viridis'`)
        - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        X = np.squeeze(X)
        assert X.ndim == 2, 'X should be two-dimensional'

        options = {} if options is None else options
        options['xmin'] = options.get('xmin', X.min())
        options['xmax'] = options.get('xmax', X.max())
        options['colormap'] = options.get('colormap', 'Viridis')
        _assert_options(options)

        data = [{
            'z': X.tolist(),
            'cmin': options['xmin'],
            'cmax': options['xmax'],
            'type': stype,
            'colorscale': options['colormap']
        }]

        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(
                options, is3d=True if stype == 'surface' else False)
        })

    def surf(self, X, win=None, env=None, options=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        `stype` is 'contour' (2D) or 'surf' (3D).

        The following `options` are supported:

        - `options.colormap`: colormap (`string`; default = `'Viridis'`)
        - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        self._surface(X=X, stype='surface', options=options, win=win, env=env)

    def contour(self, X, win=None, env=None, options=None):
        """
        This function draws a contour plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the contour plot.

        The following `options` are supported:

        - `options.colormap`: colormap (`string`; default = `'Viridis'`)
        - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        self._surface(X=X, stype='contour', options=options, win=win, env=env)

    def stem(self, X, Y=None, win=None, env=None, options=None):
        """
        This function draws a stem plot. It takes as input an `N` or `NxM`tensor
        `X` that specifies the values of the `N` points in the `M` time series.
        An optional `N` or `NxM` tensor `Y` containing timestamps can be given
        as well; if `Y` is an `N` tensor then all `M` time series are assumed to
        have the same timestamps.

        The following `options` are supported:

        - `options.colormap`: colormap (`string`; default = `'Viridis'`)
        - `options.legend`  : `table` containing legend names
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

        options = {} if options is None else options
        options['mode'] = 'lines'
        _assert_options(options)

        return self.scatter(X=data, Y=labels, options=options, win=win, env=env)

    def pie(self, X, win=None, env=None, options=None):
        """
        This function draws a pie chart based on the `N` tensor `X`.

        The following `options` are supported:

        - `options.legend`: `table` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1, 'X should be one-dimensional'
        assert np.all(np.greater_equal(X, 0)), \
            'X cannot contain negative values'

        options = {} if options is None else options
        _assert_options(options)

        data = [{
            'values': X.tolist(),
            'labels': options.get('legend'),
            'type': 'pie',
        }]
        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options)
        })

    def mesh(self, X, Y=None, win=None, env=None, options=None):
        """
        This function draws a mesh plot from a set of vertices defined in an
        `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or
        `Mx3` matrix `Y`.

        The following `options` are supported:

        - `options.color`: color (`string`)
        - `options.opacity`: opacity of polygons (`number` between 0 and 1)
        """
        options = {} if options is None else options
        _assert_options(options)

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
            'color': options.get('color'),
            'opacity': options.get('opacity'),
            'type': 'mesh3d' if is3d else 'mesh',
        }]
        return self._send({
            'data': data,
            'win': win,
            'eid': env,
            'layout': _options2layout(options)
        })
