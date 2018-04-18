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
