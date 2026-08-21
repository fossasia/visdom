#!/bin/sh

mkdir -p py/static/js
wget "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-svg.js" -O py/static/js/mathjax-tex-mml-svg.js
wget https://cdn.rawgit.com/plotly/plotly.js/master/dist/plotly.min.js -O py/static/js/plotly-plotly.min.js
wget https://unpkg.com/sjcl@1.0.7/sjcl.js -O py/static/js/sjcl.js


mkdir -p py/static/css
wget https://unpkg.com/react-resizable@3.1.3/css/styles.css -O py/static/css/react-resizable-styles.css
wget https://unpkg.com/react-grid-layout@2.2.3/css/styles.css -O py/static/css/react-grid-layout-styles.css


mkdir -p py/static/fonts
wget https://unpkg.com/layout-bin-packer@1.4.0/dist/layout-bin-packer.js -O py/static/fonts/layout_bin_packer

cat py/visdom/VERSION > py/visdom/static/version.built
