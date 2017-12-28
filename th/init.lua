--[[

Copyright 2017-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the license found in the
LICENSE file in the root directory of this source tree.

]]--

-- dependencies:
require 'torch'
require 'image'
local json     = require 'cjson'
local mime     = require 'mime'
local ltn12    = require 'ltn12'
local socket   = require 'socket'
socket.http    = require 'socket.http'
local argcheck = require 'argcheck'

-- make torch class:
local visdom = {}
local M = torch.class('visdom.client', visdom)

-- function that performs assertions on options:
local assertOptions = argcheck{
   {name = 'options', type = 'table'},
   call = function(options)
      if options.colormap then
         assert(type(options.colormap) == 'string', 'colormap should be string')
      end
      if options.color then
         assert(type(options.color) == 'string', 'color should be string')
      end
      if options.mode then
         assert(type(options.mode) == 'string', 'mode should be a string')
      end
      if options.markersymbol then
         assert(type(options.markersymbol) == 'string',
            'marker symbol should be string')
      end
      if options.markersize then
         assert(type(options.markersize) == 'number' or options.markersize > 0,
            'marker size should be a positive number')
      end
      if options.columnnames then
         assert(type(options.columnnames) == 'table',
            'columnnames should be a table with column names')
      end
      if options.rownames then
         assert(type(options.rownames) == 'table',
            'rownames should be a table with row names')
      end
      if options.jpgquality then
         assert(type(options.jpgquality) == 'number',
            'JPG quality should be a number')
         assert(options.jpgquality > 0 and options.jpgquality <= 100,
            'JPG quality should be number between 0 and 100')
      end
      if options.fps then
         assert(type(options.fps) == 'number', 'fps should be a number')
         assert(options.fps > 0 , 'fps should be greater than zero')
      end
      if options.opacity then
         assert(type(options.opacity) == 'number',
            'opacity should be a number')
         assert(options.opacity >= 0 and options.opacity <= 1,
            'opacity should be a number between 0 and 1')
      end
   end
}

-- initialize plotting object:
M.__init = argcheck{
   doc = [[
      The `visdom` package implements a Torch client for `visdom`, a
      visualization server that wraps plot.ly to show scalable, high-quality
      visualizations in the browser.

      The server can be started with the `server.py` script. The server defaults
      to port 8097. When the server is running on `domain.com:8097`, then visit
      that web address in your browser to see the visualization desktop.

      Next, initialize the `visdom` Torch client as follows in your Lua code:

      `plot = visdom{server = 'http://domain.com', port = 8097}`

      The client supports optional `endpoint` and `proxy` variables as input. It
      also supports an `ipv6` boolean variable as input, that forces the use of
      IPv6 when set to `true` (default = `true`).

      The visualization package is now ready for use. It currently provides the
      following visualization functions:

       - `plot.scatter`: 2D or 3D scatter plots
       - `plot.line`   : line plots
       - `plot.stem`   : stem plots
       - `plot.heatmap`: heatmap plots
       - `plot.bar`    : bar graphs
       - `plot.hist`   : histograms
       - `plot.boxplot`: boxplots
       - `plot.surf`   : surface plots
       - `plot.contour`: contour plots
       - `plot.quiver` : quiver plots
       - `plot.image`  : images
       - `plot.text`   : text box

      The exact inputs into these functions vary, although most of them take as
      input a tensor `X` than contains the data and an (optional) tensor `Y`
      that contains optional data variables (such as labels or timestamps).
      All plotting functions take as input a optional `win` that can be used
      to plot into a specific window; each plotting function also returns the
      `win` of the window it plotted in. One can also specify the `env`, (a
       workspace id), to which the visualization should be added.

      In addition, the plotting functions take an optional `options` table as
      input that can be used to change (generic or plot-specific) properties of
      the plots. All input arguments are specified in a single table; the input
      arguments are matches based on the keys they have in the input table.

      The following `options` are generic in the sense that they are the same
      for all visualizations (except `plot.image` and `plot.text`):

      - `options.title`       : figure title
      - `options.width`       : figure width
      - `options.height`      : figure height
      - `options.showlegend`  : show legend (`true` or `false`)
      - `options.xtype`       : type of x-axis (`'linear'` or `'log'`)
      - `options.xlabel`      : label of x-axis
      - `options.xtick`       : show ticks on x-axis (`boolean`)
      - `options.xtickmin`    : first tick on x-axis (`number`)
      - `options.xtickmax`    : last tick on x-axis (`number`)
      - `options.xtickstep`   : distances between ticks on x-axis (`number`)
      - `options.ytype`       : type of y-axis (`'linear'` or `'log'`)
      - `options.ylabel`      : label of y-axis
      - `options.ytick`       : show ticks on y-axis (`boolean`)
      - `options.ytickmin`    : first tick on y-axis (`number`)
      - `options.ytickmax`    : last tick on y-axis (`number`)
      - `options.ytickstep`   : distances between ticks on y-axis (`number`)
      - `options.marginleft`  : left margin (in pixels)
      - `options.marginright` : right margin (in pixels)
      - `options.margintop`   : top margin (in pixels)
      - `options.marginbottom`: bottom margin (in pixels)

      The other options are visualization-specific, and are described in the
      documentation of the functions.
   ]],
   {name = 'self',     type = 'visdom.client'},
   {name = 'server',   type = 'string',  default = 'http://localhost'},
   {name = 'endpoint', type = 'string',  default = 'events'},
   {name = 'port',     type = 'number',  default = 8097},
   {name = 'ipv6',     type = 'boolean', default = true},
   {name = 'proxy',    type = 'string',  opt = true},
   {name = 'env',      type = 'string',  default = 'main'},
   call = function(self, server, endpoint, port, ipv6, proxy, env)
      self.server   = server
      self.endpoint = endpoint
      self.port     = port
      self.ipv6     = ipv6
      self.env      = env
      if proxy then socket.http.PROXY = proxy end
   end
}

-- sends a POST request to the server:
M.sendRequest = argcheck{
   doc = [[
      This function sends specified JSON request to the Tornado server. This
      function should generally not be called by the user, unless you want to
      build the required JSON yourself. `endpoint` specifies the destination
      Tornado server endpoint for the request.
   ]],
   noordered = true,
   {name = 'self',     type = 'visdom.client'},
   {name = 'request',  type = 'table'},
   {name = 'endpoint', type = 'string',  opt = true},
   call = function(self, request, endpoint)
      local response = {}
      request['eid'] = request['eid'] or self.env
      request = json.encode(request)

      local status, msg = socket.http.request({
         url     = string.format('%s:%s/%s', self.server, self.port,
                     endpoint or self.endpoint),
         sink    = ltn12.sink.table(response),
         source  = ltn12.source.string(request),
         create  = self.ipv6 and socket.tcp6 or socket.tcp,
         method  = 'POST',
         headers = {
            ['content-length'] = request:len(),
            ['content-type']   = 'application/text',
         },
      })

      if not status then
         print(string.format('| visdom http request failed: %s', msg))
      end

      return table.concat(response, '')
   end
}

-- save specified envs (if currently alive on server):
M.save = argcheck{
   doc = [[
      This function allows the user to save envs that are currently alive on the
      Tornado server. The envs can be specified as a table (list) of env ids.
   ]],
   {name = 'self',     type = 'visdom.client'},
   {name = 'envs',     type = 'table'},
   call = function(self, envs)
      local args = {envs}
      local kwargs = {}
      return self:py_func{func = 'save', args = args, kwargs = kwargs}
   end
}

-- check to see if a window exists
M.win_exists = argcheck{
   doc = [[
      This function returns a bool representing whether or not a window exists
      on the server already.
   ]],
   {name = 'self', type = 'visdom.client'},
   {name = 'win',  type = 'string'},
   {name = 'env',  type = 'string', opt = true},
   call = function(self, win, env)
      local args = {win}
      local kwargs = {env = env}
      local val = self:py_func{
         func = '_win_exists_wrap',
         args = args,
         kwargs = kwargs,
      }
      if val == 'true' then
         return true
      end
      if val == 'false' then
         return false
      end
      error('Value returned from win_exists was not boolean')
   end
}

-- check_connection
M.check_connection = argcheck{
   doc = [[
      This function returns a bool representing whether or not the visdom
      client is connected to the server
   ]],
   {name = 'self', type = 'visdom.client'},
   call = function(self)
      if pcall(self.win_exists, self, '') then
         return true
      else
         return false
      end
   end
}

M.update_window_opts = argcheck{
   doc = [[
      This function allows pushing new options to an existing plot window
      without updating the content
   ]],
   {name = 'self',  type = 'visdom.client'},
   {name = 'win',   type = 'string'},
   {name = 'opts',  type = 'table'},
   {name = 'env',   type = 'string',        opt = true},
   call = function(self, win, opts, env)
      local args = {win, opts}
      local kwargs = {env = env}
      return self:py_func{func = 'update_window_opts', args = args, kwargs = kwargs}
   end
}

M.updateTrace = argcheck{
   doc = [[
      This function allows updating of the data of a line or scatter plot.

      It is up to the user to specify `name` of an existing trace if they want
      to add to it, and a new `name` if they want to add a trace to the plot.
      By default, if no legend is specified, the `name` is the index of the line
      in the legend.

      If no `name` is specified, all traces should be updated.
      Update data that is all NaN is ignored (can be used for masking updates).

      The `append` parameter determines if the update data should be appended to
      or replaces existing data.

      There are less options because they are assumed to inherited from the
      specified plot.
   ]],
   {name = 'self',         type = 'visdom.client'},
   {name = 'Y',            type = 'torch.*Tensor'},
   {name = 'X',            type = 'torch.*Tensor'},
   {name = 'win',          type = 'string'},
   {name = 'env',          type = 'string',        opt = true},
   {name = 'name',         type = 'string',        opt = true},
   {name = 'append',       type = 'boolean',       opt = true},
   {name = 'opts',         type = 'table',         opt = true},
   {name = 'options',      type = 'table',         opt = true},
   call = function(self, Y, X, win, env, name, append, opts, options)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X, Y, win}
      local kwargs = {name = name, append = append, env = env, opts = opts}
      return self:py_func{func = 'updateTrace', args = args, kwargs = kwargs}
   end
}

-- scatter plot:
M.scatter = argcheck{
   doc = [[
      This function draws a 2D or 3D scatter plot. It takes as input an `Nx2` or
      `Nx3` tensor `X` that specifies the locations of the `N` points in the
      scatter plot. An optional `N` tensor `Y` containing discrete labels that
      range between `1` and `K` can be specified as well -- the labels will be
      reflected in the colors of the markers.

      `update` can be used to efficiently update the data of an existing line.
      Use 'append' to append data, 'replace' to use new data, or nil otherwise.
      Update data that is all NaN is ignored (can be used for masking updates).

      The following `options` are supported:

       - `options.colormap`    : colormap (`string`; default = `'Viridis'`)
       - `options.markersymbol`: marker symbol (`string`; default = `'dot'`)
       - `options.markersize`  : marker size (`number`; default = `'10'`)
       - `options.markercolor` : marker color (`torch.*Tensor`; default = `nil`)
       - `options.legend`      : `table` containing legend names
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'Y',       type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',         opt = true},
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   {name = 'update',  type = 'string',        opt = true},
   call = function(self, X, Y, opts, options, win, env, update)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {
         Y = Y,
         win = win,
         env = env,
         opts = opts,
         update = update
      }
      return self:py_func{func = 'scatter', args = args, kwargs = kwargs}
   end
}

-- line plot:
M.line = argcheck{
   doc = [[
      This function draws a line plot. It takes as input an `N` or `NxM` tensor
      `Y` that specifies the values of the `M` lines (that connect `N` points)
      to plot. It also takes an optional `X` tensor that specifies the
      corresponding x-axis values; `X` can be an `N` tensor (in which case all
      lines will share the same x-axis values) or have the same size as `Y`.

      `update` can be used to efficiently update the data of an existing line.
      Use 'append' to append data, 'replace' to use new data, or nil otherwise.
      Update data that is all NaN is ignored (can be used for masking updates).

      The following `options` are supported:
       - `options.fillarea`    : fill area below line (`boolean`)
       - `options.colormap`    : colormap (`string`; default = `'Viridis'`)
       - `options.markers`     : show markers (`boolean`; default = `false`)
       - `options.markersymbol`: marker symbol (`string`; default = `'dot'`)
       - `options.markersize`  : marker size (`number`; default = `'10'`)
       - `options.legend`      : `table` containing legend names
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'Y',       type = 'torch.*Tensor'},
   {name = 'X',       type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',         opt = true},
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   {name = 'update',  type = 'string',        opt = true},
   call = function(self, Y, X, opts, options, win, env, update)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {Y}
      local kwargs = {X = X, win = win, env = env, opts = opts, update = update}
      return self:py_func{func = 'line', args = args, kwargs = kwargs}
   end
}

-- stem plot:
M.stem = argcheck{
   doc = [[
      This function draws a stem plot. It takes as input an `N` or `NxM` tensor
      `X` that specifies the values of the `N` points in the `M` time series.
      An optional `N` or `NxM` tensor `Y` containing timestamps can be specified
      as well; if `Y` is an `N` tensor then all `M` time series are assumed to
      have the same timestamps.

      The following `options` are supported:

       - `options.colormap`: colormap (`string`; default = `'Viridis'`)
       - `options.legend`  : `table` containing legend names
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'Y',       type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',         opt = true},
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {Y = Y, win = win, env = env, opts = opts}
      return self:py_func{func = 'stem', args = args, kwargs = kwargs}
   end
}

-- heatmap:
M.heatmap = argcheck{
   doc = [[
      This function draws a heatmap. It takes as input an `NxM` tensor `X` that
      specifies the value at each location in the heatmap.

      The following `options` are supported:

       - `options.colormap`: colormap (`string`; default = `'Viridis'`)
       - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
       - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
       - `options.columnnames`: `table` containing x-axis labels
       - `options.rownames`: `table` containing y-axis labels
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'heatmap', args = args, kwargs = kwargs}
   end
}

-- bar plot:
M.bar = argcheck{
   doc = [[
      This function draws a regular, stacked, or grouped bar plot. It takes as
      input an `N` or `NxM` tensor `X` that specifies the height of each of the
      bars. If `X` contains `M` columns, the values corresponding to each row
      are either stacked or grouped (dependending on how `options.stacked` is
      set). In addition to `X`, an (optional) `N` tensor `Y` can be specified
      that contains the corresponding x-axis values.

      The following plot-specific `options` are currently supported:

       - `options.rownames`: `table` containing x-axis labels
       - `options.stacked` : stack multiple columns in `X`
       - `options.legend`  : `table` containing legend labels
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'Y',       type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',         opt = true},
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {Y = Y, win = win, env = env, opts = opts}
      return self:py_func{func = 'bar', args = args, kwargs = kwargs}
   end
}

-- histogram:
M.histogram = argcheck{
   doc = [[
      This function draws a histogram of the specified data. It takes as input
      an `N` tensor `X` that specifies the data of which to construct the
      histogram.

      The following plot-specific `options` are currently supported:

       - `options.numbins`: number of bins (`number`; default = 30)
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'histogram', args = args, kwargs = kwargs}
   end
}

-- boxplot:
M.boxplot = argcheck{
   doc = [[
      This function draws boxplots of the specified data. It takes as input
      an `N` or an `NxM` tensor `X` that specifies the `N` data values of which
      to construct the `M` boxplots.

      The following plot-specific `options` are currently supported:

       - `options.legend`: labels for each of the columns in `X`
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'boxplot', args = args, kwargs = kwargs}
   end
}

-- 3d surface plot:
M.surf = argcheck{
   doc = [[
      This function draws a surface plot. It takes as input an `NxM` tensor `X`
      that specifies the value at each location in the surface plot.

      The following `options` are supported:

       - `options.colormap`: colormap (`string`; default = `'Viridis'`)
       - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
       - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'surf', args = args, kwargs = kwargs}
   end
}

-- contour plot:
M.contour = argcheck{
   doc = [[
      This function draws a contour plot. It takes as input an `NxM` tensor `X`
      that specifies the value at each location in the contour plot.

      The following `options` are supported:

       - `options.colormap`: colormap (`string`; default = `'Viridis'`)
       - `options.xmin`    : clip minimum value (`number`; default = `X:min()`)
       - `options.xmax`    : clip maximum value (`number`; default = `X:max()`)
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'contour', args = args, kwargs = kwargs}
   end
}

-- quiver plots;
M.quiver = argcheck{
   doc = [[
      This function draws a quiver plot in which the direction and length of the
      arrows is determined by the `NxM` tensors `X` and `Y`. Two optional `NxM`
      tensors `gridX` and `gridY` can be provided that specify the offsets of
      the arrows; by default, the arrows will be done on a regular grid.

      The following `options` are supported:

       - `options.normalize`:  length of longest arrows (`number`)
       - `options.arrowheads`: show arrow heads (`boolean`; default = `true`)
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'Y',       type = 'torch.*Tensor'},
   {name = 'gridX',   type = 'torch.*Tensor', opt = true},
   {name = 'gridY',   type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',         opt = true},
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, gridX, gridY, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X, Y}
      local kwargs = {
         gridX = gridX,
         gridY = gridY,
         win = win,
         env = env,
         opts = opts,
      }
      return self:py_func{func = 'quiver', args = args, kwargs = kwargs}
   end
}

-- pie chart:
M.pie = argcheck{
   doc = [[
      This function draws a pie chart based on the `N` tensor `X`.

      The following `options` are supported:

       - `options.legend`: `table` containing legend names
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'pie', args = args, kwargs = kwargs}
   end
}

-- mesh plot:
M.mesh = argcheck{
   doc = [[
      This function draws a mesh plot from a set of vertices defined in an
      `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or
      `Mx3` matrix `Y`.

      The following `options` are supported:

      - `options.color`: color (`string`)
      - `options.opacity`: opacity of polygons (`number` between 0 and 1)
   ]],
   {name = 'self',    type = 'visdom.client'},
   {name = 'X',       type = 'torch.*Tensor'},
   {name = 'Y',       type = 'torch.*Tensor', opt = true},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, Y, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {X}
      local kwargs = {Y = Y, win = win, env = env, opts = opts}
      return self:py_func{func = 'mesh', args = args, kwargs = kwargs}
   end
}

-- image:
M.image = argcheck{
   doc = [[
      This function draws an img. It takes as input an `CxHxW` tensor `img`
      that contains the image.

      The following `options` are supported:

       - `options.jpgquality`: JPG quality (`number` 0-100; default = 100)
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'img',     type = 'torch.*Tensor'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, img, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {img}
      local kwargs = {win = win, env = env, opts = opts}
      return self:py_func{func = 'image', args = args, kwargs = kwargs}
   end
}

--images:
M.images = argcheck{
   doc = [[
      This function makes a grid of images. It takes either a table of image
      Tensors H x W (greyscale) or nChannel x H x W (color), or a single Tensor
      of size batchSize x nChannel x H x W or nChannel x H x W where
      nChannel=[3,1], batchSize x H x W or H x W.
   ]],
   noordered = true,
   force = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'table',   type = 'table',  opt = true},
   {name = 'tensor',  type = 'torch.*Tensor', opt = true},
   {name = 'nrow',    type = 'number', opt = true},
   {name = 'padding', type = 'number', opt = true},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, table, tensor, nrow, padding, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      assert(table or tensor)
      local input = table or tensor
      local args = {input}
      local kwargs = {
         nrow = nrow,
         padding = padding,
         win = win,
         env = env,
         opts = opts
      }
      return self:py_func{func = 'images', args = args, kwargs = kwargs}
   end
}

-- SVG object:
M.svg = argcheck{
   doc = [[
      This function draws an SVG object. It takes as input an SVG string or the
      name of an SVG file. The function does not support any plot-specific
      `options`.
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'svgstr',  type = 'string', opt = true},
   {name = 'svgfile', type = 'string', opt = true},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, svgstr, svgfile, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {}
      local kwargs = {
         svgstr = svgstr,
         svgfile = svgfile,
         win = win,
         env = env,
         opts = opts,
      }
      self:py_func{func = 'svg', args = args, kwargs = kwargs}
   end
}

-- video file:
M.video = argcheck{
   doc = [[
      This function plays a video. It takes as input the filename of the video
      or a `LxCxHxW` tensor containing all the frames of the video. The function
      does not support any plot-specific `options`.
   ]],
   noordered = true,
   {name = 'self',      type = 'visdom.client'},
   {name = 'tensor',    type = 'torch.ByteTensor', opt = true},
   {name = 'videofile', type = 'string', opt = true},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options',   type = 'table',  opt = true},
   {name = 'win',       type = 'string', opt = true},
   {name = 'env',       type = 'string', opt = true},
   call = function(self, tensor, videofile, opts, options, win, env)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {}
      local kwargs = {
         tensor = tensor,
         videofile = videofile,
         win = win,
         env = env,
         opts = opts,
      }
      return self:py_func{func = 'video', args = args, kwargs = kwargs}
   end
}

-- text:
M.text = argcheck{
   doc = [[
      This function prints text in a box. It takes as input an `text` string.
      No specific `options` are currently supported.
   ]],
   noordered = true,
   {name = 'self',    type = 'visdom.client'},
   {name = 'text',    type = 'string'},
   {name = 'opts',    type = 'table',  opt = true},
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   {name = 'append',  type = 'boolean', opt = true},
   call = function(self, text, opts, options, win, env, append)
      if options then
         print(
            [[WARNING: Argument `options` is deprecated and will soon be
            removed. Use argument `opts` instead.]]
         )
      end
      opts = opts or options or {}
      local args = {text}
      local kwargs = {win = win, env = env, opts = opts, append = append}
      return self:py_func{func = 'text', args = args, kwargs = kwargs}
   end
}

-- close a window:
M.close = argcheck{
   doc = [[
      This function closes a specific window.
      Use `win = nil` to close all windows in an env.
   ]],
   noordered = true,
   {name = 'self', type = 'visdom.client'},
   {name = 'win',  type = 'string', opt = true},
   {name = 'env',  type = 'string', opt = true},
   call = function(self, win, env)
      local args = {}
      local kwargs = {win = win, env = env}
      return self:py_func{func = 'close', args = args, kwargs = kwargs}
   end
}

-- delete an environment:
M.delete_env = argcheck{
   doc = [[
      This function deletes a specific environment.
   ]],
   noordered = true,
   {name = 'self', type = 'visdom.client'},
   {name = 'env',  type = 'string'},
   call = function(self, win, env)
      local args = {env}
      local kwargs = {}
      return self:py_func{func = 'delete_env', args = args, kwargs = kwargs}
   end
}

local prep
prep = function(v)
  local a = {val = v, is_tensor = false, is_table = false}
  if torch.isTensor(v) then
     a.val = mime.b64(torch.serialize(v, 'binary'))
     a.is_tensor = true
  end

  if type(v) == "table" then
     local vprep = {}
     for k,v_old in pairs(v) do vprep[k] = prep(v_old) end
     a.val = vprep
     a.is_table = true
  end
  return a
end

M.py_func = argcheck {
  doc = [[
  ]],
  noordered = true,
  {name = 'self', type = 'visdom.client'},
  {name = 'func', type = 'string'},
  {name = 'args', type = 'table'},
  {name = 'kwargs', type = 'table', opt=true},
  call = function(self, func, args, kwargs)
     for k,v in pairs(args) do args[k] = prep(v) end

     for k,v in pairs(kwargs or {}) do
       kwargs[k] = prep(v)
       if k == 'options' then
         kwargs.opts = kwargs.options
         kwargs.options = nil
       end
     end

     local ret = self:sendRequest{
        request = {func = func, args = args, kwargs = kwargs},
     }

     if ret:match('Traceback') then
       error(ret)
     end

     return ret
  end
}


return visdom.client
