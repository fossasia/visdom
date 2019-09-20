#!/bin/sh

mkdir -p py/static/js
wget https://unpkg.com/jquery@3.1.1/dist/jquery.min.js -O py/static/js/jquery.min.js
wget https://unpkg.com/bootstrap@3.3.7/dist/js/bootstrap.min.js -O py/static/js/bootstrap.min.js
wget https://unpkg.com/react@16.2.0/umd/react.production.min.js -O py/static/js/react-react.min.js
wget https://unpkg.com/react-dom@16.2.0/umd/react-dom.production.min.js -O py/static/js/react-dom.min.js
wget "https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-AMS-MML_SVG" -O py/static/js/mathjax-MathJax.js
wget https://cdn.rawgit.com/plotly/plotly.js/master/dist/plotly.min.js -O py/static/js/plotly-plotly.min.js
wget https://unpkg.com/sjcl@1.0.7/sjcl.js -O py/static/js/sjcl.js
wget https://cdnjs.cloudflare.com/ajax/libs/react-modal/3.6.1/react-modal.min.js -o py/static/js/react-modal.min.js


mkdir -p py/static/css
wget https://unpkg.com/react-resizable@1.4.6/css/styles.css -O py/static/css/react-resizable-styles.css
wget https://unpkg.com/react-grid-layout@0.16.3/css/styles.css -O py/static/css/react-grid-layout-styles.css
wget https://unpkg.com/bootstrap@3.3.7/dist/css/bootstrap.min.css -O py/static/css/bootstrap.min.css


mkdir -p py/static/fonts
wget https://unpkg.com/classnames@2.2.5 -O py/static/fonts/classnames
wget https://unpkg.com/layout-bin-packer@1.4.0/dist/layout-bin-packer.js -O py/static/fonts/layout_bin_packer
wget https://unpkg.com/bootstrap@3.3.7/dist/fonts/glyphicons-halflings-regular.eot -O py/static/fonts/glyphicons-halflings-regular.eot
wget https://unpkg.com/bootstrap@3.3.7/dist/fonts/glyphicons-halflings-regular.woff2 -O py/static/fonts/glyphicons-halflings-regular.woff2
wget https://unpkg.com/bootstrap@3.3.7/dist/fonts/glyphicons-halflings-regular.woff -O py/static/fonts/glyphicons-halflings-regular.woff
wget https://unpkg.com/bootstrap@3.3.7/dist/fonts/glyphicons-halflings-regular.ttf -O py/static/fonts/glyphicons-halflings-regular.ttf
wget "https://unpkg.com/bootstrap@3.3.7/dist/fonts/glyphicons-halflings-regular.svg#glyphicons_halflingsregular" -O py/static/fonts/glyphicons-halflings-regular.svg#glyphicons_halflingsregular

cat py/visdom/VERSION > py/visdom/static/version.built
