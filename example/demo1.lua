--[[

Copyright 2017-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the license found in the
LICENSE file in the root directory of this source tree.

]]--

-- dependencies:
require 'torch'
require 'image'
local paths = require 'paths'

-- intialize visdom Torch client:
local visdom = require 'visdom'
local plot = visdom{server = 'http://localhost', port = 8097}

-- text box demo:
local textwindow = plot:text{text = 'Hello, world!'}

-- image demo:
plot:image{
   img = image.fabio(),
   options = {
      title = 'Fabio',
      caption = 'Hello, I am Fabio ;)',
   }
}

-- images demo:
plot:images{
   table = {torch.zeros(3, 200, 200) + 0.1, torch.zeros(3, 200, 200) + 0.2},
   options = {
      caption = 'I was a table of tensors...',
   }
}

-- images demo:
plot:images{
   tensor = torch.randn(6, 3, 200, 200),
   options = {
     caption = 'I was a 4D tensor...',
   }
}

-- scatter plot demos:
plot:scatter{
   X = torch.randn(100, 2),
   Y = torch.randn(100):gt(0):add(1):long(),
   options = {
      legend = {'Apples', 'Pears'},
      xtickmin  = -5,
      xtickmax  = 5,
      xtickstep = .5,
      ytickmin  = -5,
      ytickmax  = 5,
      ytickstep = .5,
      markersymbol = 'cross-thin-open',
   }
}
plot:scatter{
   X = torch.randn(100, 3),
   Y = torch.randn(100):gt(0):add(1):long(),
   options = {
      markersize = 5,
      legend = {'Men', 'Women'},
   },
}

-- 2D scatterplot with custom intensities (red channel):
local id = plot:scatter{
    X = torch.randn(255, 2),
    options = {
        markersize = 10,
        markercolor = torch.zeros(255):random(0, 255),
    },
}

plot:updateTrace{                             -- add new trace to scatter plot
   X = torch.randn(255),
   Y = torch.randn(255),
   win = id,
   name = 'new trace',
   options = {markercolor = torch.zeros(255):random(0, 255)}
}

-- 2D scatter plot with custom colors:
plot:scatter{
    X = torch.randn(255, 2),
    options = {
        markersize = 10,
        markercolor = torch.zeros(255, 3):random(0, 255),
    },
}

-- 2D scatter plot with custom colors per label:
plot:scatter{
    X = torch.randn(255, 2),
    Y = torch.randn(255):gt(0):add(1):long(), -- two labels
    options = {
        markersize = 10,
        markercolor = torch.zeros(2, 3):random(0, 255),
    },
}

-- bar plot demos:
plot:bar{
   X = torch.randn(20)
}
plot:bar{
   X = torch.randn(5, 3):abs(),
   options = {
      stacked = true,
      legend = {'Facebook', 'Google', 'Twitter'},
      rownames = {'2012', '2013', '2014', '2015', '2016'},
   },
}
plot:bar{
   X = torch.randn(20, 3),
   options = {
      stacked = false,
      legend  = {'The Netherlands', 'France', 'United States'},
   },
}

-- histogram demo:
plot:histogram{
   X = torch.randn(10000),
   options = {numbins = 20},
}

-- heatmap demo:
local X = torch.cmul(torch.range(1, 10):reshape(1, 10):expand(5, 10),
                     torch.range(1, 5):reshape(5, 1):expand(5, 10))
plot:heatmap{
   X = X,
   options = {
       columnnames = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'},
       rownames = {'y1', 'y2', 'y3', 'y4', 'y5'},
       colormap = 'Electric',
   },
}

-- contour plot demo:
local x = torch.range(1, 100):reshape(1, 100):expand(100, 100)
local y = torch.range(1, 100):reshape(100, 1):expand(100, 100)
local X = torch.add(x, -50):pow(2):add(
   torch.add(y, -50):pow(2)
):div(-math.pow(20, 2)):exp()
plot:contour{X = X, options = {colormap = 'Viridis'}}

-- surface plot demo:
plot:surf{X = X, options = {colormap = 'Hot'}}

-- line plot demos:
local Y = torch.range(-4, 4, 0.05)
plot:line{
   Y = torch.cat(torch.cmul(Y, Y), torch.sqrt(Y + 5), 2),
   X = torch.cat(Y, Y, 2),
   options = {markers = false}
}

local id = plot:line{
   Y = torch.cat(torch.range(0, 10), torch.range(0, 10) + 5, 2),
   X = torch.cat(torch.range(0, 10), torch.range(0, 10), 2),
   options = {markers = false}
}

-- update trace demos:
plot:line{
   X = torch.cat(torch.range(11, 20), torch.range(11, 20), 2),
   Y = torch.cat(torch.range(11, 20), torch.range(5, 14) * 2 + 5, 2),
   win = id,
   update = 'append',
}

plot:updateTrace{
   X = torch.range(1, 10),
   Y = torch.range(1, 10),
   win = id,
   name = '3',
}

plot:updateTrace{
   X = torch.range(1, 10),
   Y = torch.range(11, 20),
   win = id,
   name = '4',
   options = {markercolors = torch.zeros(1):random(0, 255)},
}

-- stacked line plot demo:
local Y = torch.range(0, 4, 0.02)
plot:line{
   Y = torch.cat(torch.sqrt(Y), torch.sqrt(Y):add(2), 2),
   X = torch.cat(Y, Y, 2),
   options = {
      fillarea = true,
      legend   = false,
      width    = 400,
      height   = 400,
      xlabel   = 'Time',
      ylabel   = 'Volume',
      ytype    = 'log',
      title    = 'Stacked area plot',
      marginleft   = 30,
      marginright  = 30,
      marginbottom = 80,
      margintop    = 30,
   },
}

-- boxplot demo:
local X = torch.randn(100, 2)
X:narrow(2, 2, 1):add(2)
plot:boxplot{
   X = X,
   options = {
      legend = {'Men', 'Women'},
   },
}

-- stem plot demo:
local Y = torch.range(0, 2 * math.pi, (2 * math.pi) / 70)
local X = torch.cat(torch.sin(Y), torch.cos(Y), 2)
plot:stem{
   X = X,
   Y = Y,
   options = {
      legend = {'Sine', 'Cosine'},
   },
}

-- quiver demo:
local X = torch.range(0, 2, 0.2)
local Y = torch.range(0, 2, 0.2)
X = X:resize(1, X:nElement()):expand(X:nElement(), X:nElement())
Y = Y:resize(Y:nElement(), 1):expand(Y:nElement(), Y:nElement())
local U = torch.cos(X):cmul(Y)
local V = torch.sin(X):cmul(Y)
plot:quiver{
   X = U,
   Y = V,
   options = {normalize = 0.9},
}

-- pie chart demo:
local X = torch.DoubleTensor{19, 26, 55}
local legend = {'Residential', 'Non-Residential', 'Utility'}
plot:pie{
   X = X,
   options = {legend = legend},
}

-- svg rendering demo:
local svgstr = [[
<svg height="300" width="300">
  <ellipse cx="80" cy="80" rx="50" ry="30"
   style="fill:red;stroke:purple;stroke-width:2" />
  Sorry, your browser does not support inline SVG.
</svg>
]]
plot:svg{
   svgstr  = svgstr,
   options = {
      title  = 'Example of SVG Rendering',
   },
}

-- mesh plot demo:
local X = torch.DoubleTensor{
   {0, 0, 1, 1, 0, 0, 1, 1},
   {0, 1, 1, 0, 0, 1, 1, 0},
   {0, 0, 0, 0, 1, 1, 1, 1},
}:t()
local Y = torch.DoubleTensor{
   {7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2},
   {3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3},
   {0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6},
}:t()
plot:mesh{X = X, Y = Y, options = {opacity = 0.5}}

-- video demo:
local video = torch.ByteTensor(256, 3, 128, 128)
for n = 1,video:size(1) do
   video[n]:fill(n - 1)
end
local ok = pcall(plot.video, plot.video, {tensor = video})
if not ok then print('Skipped video example') end

-- video demo:
local videofile = '/home/' .. os.getenv('USER') .. '/trailer.ogv'
   -- NOTE: Download video from http://media.w3.org/2010/05/sintel/trailer.ogv
if paths.filep(videofile) then
   local ok = pcall(plot.video, plot.video, {videofile = videofile})
   if not ok then print('Skipped video example') end
end

-- close text window:
plot:close{win = textwindow}
