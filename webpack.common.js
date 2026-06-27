/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

var webpack = require('webpack');
var path = require('path');

module.exports = {
  entry: ['./js/main.js'],
  output: {
    path: path.join(__dirname, './'),
    filename: 'py/visdom/static/js/main.js',
  },
  resolve: {
    fallback: {
      net: false,
      dns: false,
      stream: require.resolve('stream-browserify'),
      zlib: require.resolve('browserify-zlib'),
      util: require.resolve('util'),
      https: require.resolve('https-browserify'),
      http: require.resolve('stream-http'),
      fetch: require.resolve('whatwg-fetch'),
    },
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /(node_modules|bower_components)/,
        loader: 'babel-loader',
        options: {
          presets: ['@babel/preset-env', '@babel/preset-react'],
          plugins: ['@babel/plugin-proposal-class-properties'],
        },
      },
      {
        test: /\.mjs$/,
        include: /node_modules/,
        type: 'javascript/auto',
        resolve: {
          fullySpecified: false,
        },
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader'],
      },
      {
        test: /\.less$/,
        use: [
          'style-loader',
          'css-loader',
          {
            loader: 'less-loader',
            options: {
              lessOptions: {
                javascriptEnabled: true,
              },
            },
          },
        ],
      },
    ],
  },
  plugins: [
    new webpack.BannerPlugin('@generated'),
    new webpack.DefinePlugin({
      'process.env': JSON.stringify({}),
    }),
    // new webpack.ProvidePlugin({
    //   Buffer: ['buffer', 'Buffer']
    // })
  ],
};
