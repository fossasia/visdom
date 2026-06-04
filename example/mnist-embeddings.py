#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import visdom
import numpy as np
from PIL import Image  # type: ignore
import base64 as b64  # type: ignore
from io import BytesIO
import sys

try:
    features = np.loadtxt("example/data/mnist2500_X.txt")
    labels = np.loadtxt("example/data/mnist2500_labels.txt")
except OSError:
    print("Unable to find files mmist2500_X.txt and mnist2500_labels.txt "
          "in the example/data/ directory. Please download from "
          "https://github.com/lvdmaaten/lvdmaaten.github.io/"
          "blob/master/tsne/code/tsne_python.zip")
    sys.exit()

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
    return "<img src='" + display_data + "' />"


vis.embeddings(features, labels, data_getter=get_mnist_for_index, data_type='html')

input('Waiting for callbacks, press enter to quit.')
