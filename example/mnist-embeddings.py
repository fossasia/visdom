# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import visdom
import numpy as np
from PIL import Image  # type: ignore
import base64 as b64  # type: ignore
from six import BytesIO

features = np.loadtxt("examples/data/mnist2500_x.txt")
labels = np.loadtxt("examples/data/mnist2500_labels.txt")
vis = visdom.Visdom()

image_datas = []
for feat in features:
    img_array = np.flipud(np.rot90(np.reshape(feat, (28, 28))))
    im = Image.fromarray(img_array * 255)
    im = im.convert('RGB')
    buf = BytesIO()
    im.save(buf, format='PNG')
    b64encoded = b64.b64encode(buf.getvalue()).decode('utf-8')
    image_datas.append(b64encoded)


def get_mnist_for_index(id):
    image_data = image_datas[id]
    display_data = 'data:image/png;base64,' + image_data
    return "<img src='"+display_data+"' />"


vis.embeddings(features, labels, data_getter=get_mnist_for_index, data_type='html')

input('Waiting for callbacks, press enter to quit.')
