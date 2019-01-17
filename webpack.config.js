/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

module.exports = {
  entry: [
    './js/main.js',
  ],
  output: {
    filename: 'py/visdom/static/js/main.js'
  },
  module: {
    loaders: [
      {
        test: /\.js$/,
        exclude: /(node_modules|bower_components)/,
        loader: 'babel-loader',
        query: {
          presets: [
            'es2015',
            'react',
          ],
          plugins: [
            'transform-class-properties',
          ],
        }
      },
      {
        test: /\.css$/,
        loaders: [ 'style', 'css' ]
      }
    ]
  },
}
