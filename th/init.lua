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
local ffi      = require 'ffi'
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

-- function that replaces all NaNs in a table by json.null:
local function _nan2null(t)
   for key, val in pairs(t) do
      if type(val) == 'table' then
         t[key] = _nan2null(val)
      elseif val ~= val then
         t[key] = json.null
      end
   end
   return t
end
local nan2null = argcheck{
   {name = 't', type = 'table'},
   call = function(t)
      return _nan2null(t)
   end
}

-- function that parses the layout from options:
local options2layout = argcheck{
   noordered = true,
   {name = 'options', type = 'table'},
   {name = 'is3d',    type = 'boolean', default = false},
   call = function(options, is3d)
      local layout = {
         width      = options.width,
         height     = options.height,
         showlegend = (options.legend == nil) and false or options.legend,
         title      = options.title,
         xaxis = (options.xtype or options.xtype or options.xtick or
            options.xtickvals or options.xticklabels or options.xlabel or
            options.xtickmin or options.xtickmax) and {
            type     = options.xtype,
            title    = options.xlabel,
            tickvals = options.xtickvals,
            ticktext = options.xticklabels,
            range    = (options.xtickmin and options.xtickmax) and
               {options.xtickmin, options.xtickmax} or nil,
            tickwidth      = options.xtickstep,
            showticklabels = options.xtick,
         },
         yaxis = (options.ytype or options.ytype or options.ytick or
            options.ytickvals or options.yticklabels or options.ylabel or
            options.ytickmin or options.ytickmax) and {
            type     = options.ytype,
            title    = options.ylabel,
            tickvals = options.ytickvals,
            ticktext = options.yticklabels,
            range    = (options.ytickmin and options.ytickmax) and
               {options.ytickmin, options.ytickmax} or nil,
            tickwidth      = options.ytickstep,
            showticklabels = options.ytick,
         },
         margin = {
            l = options.marginleft or 60,
            r = options.marginright or 60,
            t = options.margintop or 60,
            b = options.marginbottom or 60,
         },
      }
      if is3d then
         layout.zaxis = (options.ztype or options.ztype or options.ztick or
            options.ztickvals or options.zticklabels or options.zlabel or
            options.ztickmin or options.ztickmax) and {
            type     = options.ztype,
            title    = options.zlabel,
            tickvals = options.ztickvals,
            ticktext = options.zticklabels,
            range = (options.ztickmin and options.ztickmax) and
               {options.ztickmin, options.ztickmax} or nil,
            tickwidth      = options.ztickstep,
            showticklabels = options.ztick,
         }
      end
      if options.stacked ~= nil then
         layout.barmode = options.stacked and 'stack' or 'group'
      end
      return layout
   end
}

local markerColorCheck = argcheck{
   noordered = true,
   {name = 'mc',        type = 'torch.*Tensor'},
   {name = 'X',         type = 'torch.*Tensor'},
   {name = 'Y',         type = 'torch.*Tensor'},
   {name = 'numlabels', type = 'number'},
   call = function(mc, X, Y, numlabels)
      assert(torch.isTensor(mc), "markercolor need to be a torch.*Tensor")
      assert(mc:size(1) == numlabels or (mc:size(1) == X:size(1) and
              (mc:dim() == 1 or mc:dim() == 2 and mc:size(2) == 3)),
             string.format("marker colors have to be of size `%d` " ..
                              "or `%d x 3` or `%d` or `%d x 3`, " ..
                              "but got: %s", X:size(1), X:size(1),
                           numlabels, numlabels,
                           table.concat(mc:size():totable(), 'x')))
      assert(mc:ge(0):all(), "marker colors have to be >= 0")
      assert(mc:le(255):all(), "marker colors have to be <= 255")
      assert(mc:eq(torch.floor(mc)):all(),
             'marker colors are assumed to be integer')

      local markercolor
      if mc:dim() == 1 then  -- mc = N
          markercolor = mc:totable()
      else  -- mc = N x 3
          markercolor = {}
          for i = 1, mc:size(1) do
              markercolor[i] = string.format('#%x%x%x', mc[i][1],
                                                     mc[i][2], mc[i][3])
          end
      end
      if mc:size(1) ~= X:size(1) then
        local ret = {}
        for i = 1, Y:size(1) do
            ret[i] = markercolor[Y[i]]
        end
        markercolor = ret
      end
      local ret = {}
      for k,v in pairs(markercolor) do
        ret[Y[k]] = ret[Y[k]] or {}
        table.insert(ret[Y[k]], v)
      end
      return ret
   end
}

-- initialize plotting object:
M.__init = argcheck{
   doc = [[
      The `visdom` package implements a Torch client for `visdom`, a visualization
      server that wraps plot.ly to show scalable, high-quality visualizations in
      the browser.

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
      if #envs > 0 then
         for _,v in pairs(envs) do assert(type(v) == 'string') end

         -- send save request to server
         return self:sendRequest{
            request = {
               data = envs,
            },
            endpoint = 'save',
         }
      end
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
   {name = 'options',      type = 'table',         opt = true},
   call = function(self, Y, X, win, env, name, append, options)

      -- assertions on the inputs:
      assert(Y:isSameSizeAs(X), 'Y should be same size as X')
      assert(X:dim() == 1 or X:dim() == 2, 'Updated X should be 1 or 2 dim')
      if name then
         assert(#name >= 0,   'name of trace should be nonempty string')
         assert(X:dim() == 1, 'updating by name expects 1-dim data')
      end
      options = options or {}
      if options.markercolor then
         options.markercolor = markerColorCheck{
            mc        = options.markercolor,
            X         = X,
            Y         = X.new(X:size()):fill(1),
            numlabels = 1,
         }
      end

      -- generate table in plotly format:
      local data = {
         x = X:view(X:size(1), -1):t():totable(),
         y = Y:view(Y:size(1), -1):t():totable(),
      }
      if options.markercolor then  -- for scatter plot
         data.marker = {color = options.markercolor}
      end

      -- send scatter plot request to server:
      return self:sendRequest{
         request = {
            data      = nan2null(data),
            win       = win,
            eid       = env,
            name      = name,
            append    = append,
            opts      = options,
         },
         endpoint = 'update',
      }
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
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   {name = 'update',  type = 'string',        opt = true},
   call = function(self, X, Y, options, win, env, update)

      if update then
         return self:updateTrace{Y = Y, X = X, win = win, env = env,
            options = options, append = update == 'append',
         }
      end

      -- assertions on inputs:
      assert(X:dim() == 2, 'X should be two-dimensional')
      assert(X:size(2) == 2 or X:size(2) == 3,
         'X should have two or three columns')
      if Y then
         Y = Y:squeeze()
         assert(Y:dim() == 1, 'Y should be one-dimensional')
         assert(X:size(1) == Y:size(1), 'sizes of X and Y should match')
      else
         Y = torch.ones(X:size(1))
      end
      assert(not(torch.typename(Y) == 'torch.FloatTensor' or
                 torch.typename(Y) == 'torch.DoubleTensor') or
         Y:eq(torch.floor(Y)):all(), 'labels are assumed to be integer')
      assert(Y:min() == 1, 'labels are assumed to be between 1 and K')
      local numlabels, is3d = Y:max(), (X:size(2) == 3)

      -- set default options:
      options = options or {}
      options.colormap     = options.colormap     or 'Viridis'
      options.mode         = options.mode         or 'markers'
      options.markersymbol = options.markersymbol or 'dot'
      options.markersize   = options.markersize   or 10
      if options.markercolor ~= nil then
         options.markercolor = markerColorCheck{
            mc          = options.markercolor,
            X           = X,
            Y           = Y,
            numlabels   = numlabels,
         }
      end
      assertOptions{options = options}
      if options.legend then
         assert(#options.legend == numlabels,
            'number of legend labels must match number of labels in Y')
      end

      -- generate table in plotly format:
      local data = {}
      for k = 1,numlabels do
         local ind = Y:eq(k)
         if ind:sum() > 0 then  -- ignore classes without data
            table.insert(data, {
               x      = X:select(2, 1)[ind]:totable(),
               y      = X:select(2, 2)[ind]:totable(),
               z      = is3d and X:select(2, 3)[ind]:totable() or nil,
               name   = options.legend and
                        options.legend[k] or string.format('%d', k),
               type   = is3d and 'scatter3d' or 'scatter',
               mode   = options.mode,
               fill   = options.fillarea and 'tonexty' or nil,
               marker = {
                  size   = options.markersize,
                  symbol = options.markersymbol,
                  color  = options.markercolor and options.markercolor[k] or nil,
                  line   = {
                     color = '#000000',
                     width = 0.5,
                  },
               },
            })
         end
      end

      -- send scatter plot request to server:
      return self:sendRequest{request = {
         data   = nan2null(data),
         win    = win,
         eid    = env,
         layout = options2layout{options = options, is3d = is3d},
         opts   = options,
      }}
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
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   {name = 'update',  type = 'string',        opt = true},
   call = function(self, Y, X, options, win, env, update)

      if update then
         if Y:dim() == 2 and X:dim() == 1 then
            X = X:reshape(X:nElement(), 1):expandAs(Y)
         end
         return self:updateTrace{Y = Y, X = X, win = win, env = env,
            options = options, append = update == 'append',
         }
      end

      -- assertions on the inputs:
      assert(Y:dim() == 1 or Y:dim() == 2, 'Y should be one or two-dimensional')
      if X then
         assert(X:dim() == 1 or X:dim() == 2,
            'X should be one or two-dimensional')
      else
         X = torch.linspace(0, 1, Y:size(1))
      end
      if Y:dim() == 2 and X:dim() == 1 then
         X = X:reshape(X:nElement(), 1):expandAs(Y)
      end
      assert(Y:isSameSizeAs(X), 'data should have the same size')

      -- set default options:
      options = options or {}
      options.markers  = (options.markers == nil) and false or options.markers
      options.fillarea = (options.fillarea == nil) and false or options.fillarea
      options.mode = options.markers and 'lines+markers' or 'lines'
      assertOptions{options = options}

      -- set up line data:
      local linedata
      if Y:dim() == 1 then
         linedata = torch.cat(X, Y, 2)
      else
         linedata = torch.cat(X:t():reshape(X:nElement(), 1),
                              Y:t():reshape(Y:nElement(), 1), 2)
      end

      -- set up labels indicating which line each element corresponds to:
      local labels
      if Y:dim() == 2 then
         labels = torch.range(1, Y:size(2))
         labels = labels:reshape(1, labels:nElement()):expandAs(Y)
         labels = labels:t():reshape(labels:nElement())
      end

      -- send line plot request to server (line plot is a special scatter plot):
      return (self:scatter{
         X       = linedata,
         Y       = labels,
         options = options,
         win     = win,
         env     = env
      })
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
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, options, win, env)

      -- assertions on inputs:
      local X = X:squeeze()
      assert(X:dim() == 1 or X:dim() == 2, 'X should be one or two-dimensional')
      if X:dim() == 1 then X = X:reshape(X:nElement(), 1) end
      local Y = Y or torch.range(1, X:size(1))
      if Y:dim() == 1 then Y = Y:reshape(Y:nElement(), 1) end
      assert(Y:size(1) == X:size(1), 'number of rows in X and Y should match')
      assert(Y:size(2) == 1 or Y:size(2) == X:size(2),
         'Y should be a single column or the same number of columns as X')
      if Y:size(2) < X:size(2) then Y = Y:expandAs(X) end

      -- interleave X and Y with copies / zeros to get lines:
      local Z = torch.zeros(Y:size(1), Y:size(2))         -- all zeros
      local N = torch.zeros(Y:size(1), Y:size(2)):cdiv(Z) -- all NaNs
      X = torch.cat({Z, X, N}, 2):reshape(X:size(1) * 3, X:size(2))
      Y = torch.cat({Y, Y, N}, 2):reshape(Y:size(1) * 3, Y:size(2))

      -- convert data to scatter plot format:
      local data = torch.cat(Y:reshape(Y:nElement()),
                             X:reshape(X:nElement()), 2)
      local labels = torch.range(1, X:size(2)):reshape(1, X:size(2))
      labels = labels:expandAs(X):reshape(X:nElement())

      -- set default options:
      options = options or {}
      options.mode = 'lines'
      assertOptions{options = options}

      -- generate data in plotly format (stem plot is a special scatter plot):
      return (self:scatter{
         X       = data,
         Y       = labels,
         options = options,
         win     = win,
         env     = env,
      })
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)
      assert(X:dim() == 2, 'data should be two-dimensional')

      -- set default options:
      options = options or {}
      options.xmin     = options.xmin     or X:min()
      options.xmax     = options.xmax     or X:max()
      options.colormap = options.colormap or 'Viridis'
      options.columnnames = options.columnnames or nil
      options.rownames = options.rownames or nil
      assertOptions{options = options}
      if options.columnnames then
         assert(#options.columnnames == X:size(2),
            'number of column names should match number of columns in X')
      end
      if options.rownames then
         assert(#options.rownames == X:size(1),
            'number of row names should match number of rows in X')
      end

      -- generate data in plotly format:
      local data = {{
         z    = X:totable(),
         x    = options.columnnames,
         y    = options.rownames,
         zmin = options.xmin,
         zmax = options.xmax,
         type = 'heatmap',
         colorscale = options.colormap,
      }}

      -- send heatmap plot request to server:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         layout = options2layout{options = options},
         opts   = options,
      }}
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
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, options, win, env)

      -- assertions on inputs:
      local X = X:squeeze()
      assert(X:dim() == 1 or X:dim() == 2, 'X should be one or two-dimensional')
      if X:dim() == 1 then X = X:reshape(X:nElement(), 1) end
      if Y then
         Y = Y:squeeze()
         assert(Y:dim() == 1, 'Y should be one-dimensional')
         assert(X:nElement() == Y:nElement(), 'sizes of X and Y should match')
      else
         Y = torch.range(1, X:nElement())
      end

      -- set default options:
      options = options or {}
      options.stacked = (options.stacked == nil) and false or options.stacked
      options.rownames = options.rownames or nil
      assertOptions{options = options}
      if options.rownames then
         assert(#options.rownames == X:size(1),
            'number of row names should match number of rows in X')
      end
      if options.legend then
         assert(#options.legend == X:size(2),
            'number of legend labels must match number of columns in X')
      end

      -- generate data in plotly format:
      local data = {}
      for k = 1,X:size(2) do
         table.insert(data,{
            y    = X:select(2, k):totable(),
            x    = options.rownames or Y:totable(),
            type = 'bar',
            name = options.legend and options.legend[k] or nil,
         })
      end

      -- send bar plot request to server:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         layout = options2layout{options = options},
         opts   = options,
      }}
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)

      -- assertions in inputs:
      local X = X:squeeze()
      assert(X:dim() == 1, 'X should be one-dimensional')

      -- set default options:
      options = options or {}
      options.numbins = options.numbins or math.min(30, X:nElement())
      assertOptions{options = options}

      -- compute histogram:
      local minX, maxX = X:min(), X:max()
      local bins  = torch.histc(X, options.numbins, minX, maxX)
      local range = torch.linspace(minX, maxX, options.numbins)

      -- make plot:
      return (self:bar{
         X = bins,
         Y = range,
         options = options,
         win     = win,
         env     = env,
      })
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)

      -- assertions on input:
      local X = X:squeeze()
      assert(X:dim() == 1 or X:dim() == 2, 'X should be one or two-dimensional')
      X = X:reshape(X:size(1), X:dim() == 1 and 1 or X:size(2))

      -- process options:
      options = options or {}
      assertOptions{options = options}
      if options.legend then
         assert(#options.legend == X:size(2),
            'number of legend labels should match number of columns')
      end

      -- construct data:
      local data = {}
      for k = 1,X:size(2) do
         table.insert(data, {
            type = 'box',
            y    = X:select(2, k):totable(),
            name = options.legend and options.legend[k]
                                   or string.format('column %d', k)
         })
      end

      -- send boxplot request to server:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         layout = options2layout{options = options},
         opts   = options,
      }}
   end
}

-- helper function for surface 2D/3D plots
-- `type` is 'contour' (2D) or 'surface' (3D).
local function _surface(self, X, type, options, win, env)
   -- assertions on input:
   X = X:squeeze()
   assert(X:dim() == 2, 'X should be two-dimensional')

   -- process options:
   options = options or {}
   options.xmin     = options.xmin     or X:min()
   options.xmax     = options.xmax     or X:max()
   options.colormap = options.colormap or 'Viridis'
   assertOptions{options = options}

   -- generate data table:
   local data = {{
      z    = X:totable(),
      [type == 'surface' and 'cmin' or 'zmin'] = options.xmin,
      [type == 'surface' and 'cmax' or 'zmax'] = options.xmax,
      type = type,
      colorscale = options.colormap,
   }}

   -- send 3d surface plot request to server:
   return self:sendRequest{request = {
      data   = data,
      win    = win,
      eid    = env,
      layout = options2layout{
         options = options,
         is3d = type == 'surface' and true or nil
      },
      opts   = options,
   }}
end

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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)
      return _surface(self, X, 'surface', options, win, env)
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)
      return _surface(self, X, 'contour', options, win, env)
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
   {name = 'options', type = 'table',         opt = true},
   {name = 'win',     type = 'string',        opt = true},
   {name = 'env',     type = 'string',        opt = true},
   call = function(self, X, Y, gridX, gridY, options, win, env)

      -- defaults and assertions:
      assert(X:nDimension() == 2, 'X should be two-dimensional')
      assert(Y:nDimension() == 2, 'Y should be two-dimensional')
      assert(X:isSameSizeAs(Y), 'X and Y should have the same size')
      local N, M = X:size(1), X:size(2)
      local gridY = gridY or torch.range(1, N):resize(N, 1):expand(N, M)
      local gridX = gridX or torch.range(1, M):resize(1, M):expand(N, M)
      assert(X:isSameSizeAs(gridX), 'X and gridX should have the same size')
      assert(Y:isSameSizeAs(gridY), 'Y and gridY should have the same size')

      -- set default options:
      options = options or {}
      options.mode = 'lines'
      options.arrowheads = (options.arrowheads == nil) or options.arrowheads
      assertOptions{options = options}

      -- normalize vectors to unit length:
      if options.normalize then
         assert(type(options.normalize) == 'number' and options.normalize > 0,
            'options.normalize should be a positive number')
         local magnitude = torch.cmul(X, X):add(torch.cmul(Y, Y)):sqrt():max()
         X:div(magnitude / options.normalize)
         Y:div(magnitude / options.normalize)
      end

      -- function that makes a vector:
      local function vec(tensor) return tensor:reshape(tensor:nElement()) end

      -- interleave X and Y with copies / NaNs to get lines:
      local N = vec(torch.zeros(X:size(1), X:size(2)):div(0)) -- all NaNs
      local tipX = torch.add(gridX, X)
      local tipY = torch.add(gridY, Y)
      local dX = torch.cat({vec(gridX), vec(tipX), N}, 2)
      local dY = torch.cat({vec(gridY), vec(tipY), N}, 2)

      -- convert data to scatter plot format:
      dX = dX:reshape(dX:size(1) * 3, 1)
      dY = dY:reshape(dY:size(1) * 3, 1)
      local data = torch.cat(dX:reshape(dX:nElement()),
                             dY:reshape(dY:nElement()), 2)

      -- add arrow heads:
      if options.arrowheads then

         -- compute tip points:
         local alpha = 0.33  -- size of arrow head relative to vector length
         local beta  = 0.33  -- width of the base of the arrow head
         local Xbeta = torch.add(X, 1e-5):mul(beta)
         local Ybeta = torch.add(Y, 1e-5):mul(beta)
         local lX = torch.add(X,  Ybeta):mul(-alpha):add(tipX)
         local rX = torch.add(X, -Ybeta):mul(-alpha):add(tipX)
         local lY = torch.add(Y, -Xbeta):mul(-alpha):add(tipY)
         local rY = torch.add(Y,  Xbeta):mul(-alpha):add(tipY)

         -- add to data:
         local hX = torch.cat({vec(lX), vec(tipX), vec(rX), vec(N)}, 2)
         local hY = torch.cat({vec(lY), vec(tipY), vec(rY), vec(N)}, 2)
         hX = hX:reshape(hX:size(1) * 4, 1)
         hY = hY:reshape(hY:size(1) * 4, 1)
         data = torch.cat(data, torch.cat(hX:reshape(hX:nElement()),
                                          hY:reshape(hY:nElement()), 2), 1)
      end

      -- generate data in plotly format (quiver plot is a special scatter plot):
      return (self:scatter{
         X       = data,
         options = options,
         win     = win,
         env     = env,
      })
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, options, win, env)

      -- check input:
      local X = X:squeeze()
      assert(X:nDimension() == 1,  'X should be one-dimensional')
      assert(torch.ge(X, 0):all(), 'X cannot contain negative values')

      -- generate table in plotly format:
      local data = {{
         values = X:totable(),
         labels = options.legend,
         type   = 'pie'
      }}

      -- send 3d surface plot request to server:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         layout = options2layout{options = options},
         opts   = options,
      }}
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, X, Y, options, win, env)

      -- check inputs:
      assert(X:nDimension() == 2, 'X must have 2 dimensions')
      assert(X:size(2) == 2 or X:size(2) == 3, 'X must have 2 or 3 columns')
      local is3d = (X:size(2) == 3)
      local ispoly = (Y ~= nil)
      if ispoly then
         assert(Y:nDimension() == 2, 'Y must have 2 dimensions')
         assert(Y:size(2) == X:size(2),
            'X and Y must have same number of columns')
      end
      options = options or {}
      assertOptions(options)

      -- make data object:
      local data = {{
         x = X:narrow(2, 1, 1):squeeze():totable(),
         y = X:narrow(2, 2, 1):squeeze():totable(),
         z = is3d and X:narrow(2, 3, 1):squeeze():totable() or nil,
         i = ispoly and Y:narrow(2, 1, 1):squeeze():totable() or nil,
         j = ispoly and Y:narrow(2, 2, 1):squeeze():totable() or nil,
         k = (ispoly and is3d) and Y:narrow(2, 3, 1):squeeze():totable() or nil,
         color = options.color,
         opacity = options.opacity,
         type = is3d and 'mesh3d' or 'mesh',
      }}
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         layout = options2layout{options = options},
         opts   = options,
      }}
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, img, options, win, env)
      assert(img:dim() == 2 or img:dim() == 3,
         'image should be two or three-dimensional')

      -- default options:
      options = options or {}
      options.jpgquality = options.jpgquality or 100
      assertOptions{options = options}

      -- convert to JPG bytestring to base64:
      local immem = image.compressJPG(img, options.jpgquality)
      local imgdata = 'data:image/jpg;base64,' ..
         mime.b64(ffi.string(immem:data(), immem:nElement()))
      local imsize = (img:dim() == 2 and img or img[1]):size():totable()
      options.width = (options.width or imsize[2])
      options.height = (options.height or imsize[1])

      -- make data object:
      local data = {{
         content = {
            src     = imgdata,
            caption = options.caption,
         },
         type = 'image',
      }}  -- NOTE: This is not a plotly type

      -- send image request:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         opts   = options,
      }}
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, table, tensor, nrow, padding, options, win, env)
      assert(table or tensor)
      return self:image{
        img = image.toDisplayTensor{
          input = table or tensor, padding = padding, nrow = nrow},
        options = options,
        win = win,
        env = env
      }
   end
}

-- helper function for loading file as bytestring:
local function loadFile(filename)
   local paths = require 'paths'
   assert(paths.filep(filename),
      string.format('file not found: %s', filename))
   local file = io.open(filename, 'r')
   assert(file, string.format('could not open file: %s', filename))
   local str = file:read('*all')
   file:close()
   return str
end

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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, svgstr, svgfile, options, win, env)

      -- load SVG and strip doctype if it is present:
      assert(svgstr or svgfile, 'should specify SVG string or filename')
      local svgstr = svgstr or loadFile(svgfile)
      local svg = svgstr:match('<svg .+</svg>')
      assert(svg, 'SVG could not be parsed correctly')

      -- send SVG request:
      return (self:text{
         text    = svg,
         options = options,
         win     = win,
         eid     = env,
      })
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
   {name = 'options',   type = 'table',  opt = true},
   {name = 'win',       type = 'string', opt = true},
   {name = 'env',       type = 'string', opt = true},
   call = function(self, tensor, videofile, options, win, env)

      -- get mime type for video:
      options = options or {}
      options.fps = options.fps or 25
      videofile = videofile or os.tmpname() .. '.ogv'
      assert(tensor or videofile, 'should specify video tensor or file')
      local extension = videofile:sub(-3):lower()
      local mimetypes = {
         mp4  = 'mp4',
         ogv  = 'ogg',
         avi  = 'avi',
         webm = 'webm',
      }
      local mimetype = mimetypes[extension]
      assert(mimetype, string.format('unknown video type: %s', extension))

      -- construct video if a tensor was specified:
      if tensor then
         assert(tensor:nDimension() == 4, 'video should be in 4D tensor')
         local ffmpeg = require 'ffmpeg'
         local video = ffmpeg.Video{
            height = tensor:size(3),
            width  = tensor:size(4),
            fps    = options.fps,
            length = tensor:size(1),
            tensor = tensor,
            zoom   = 2,
         }
         video:save{outpath = videofile, keep = false, usetheora = true}
      end

      -- load video file:
      local bytestr = loadFile(videofile)

      -- send out video request:
      local videodata = string.format([[
         <video controls>
            <source type="video/%s" src="data:video/%s;base64,%s">
            Your browser does not support the video tag.
         </video>
      ]], mimetype, mimetype, mime.b64(bytestr))
      return (self:text{
         text    = videodata,
         options = options,
         win     = win,
         eid     = env,
      })
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
   {name = 'options', type = 'table',  opt = true},
   {name = 'win',     type = 'string', opt = true},
   {name = 'env',     type = 'string', opt = true},
   call = function(self, text, options, win, env)

      -- default options:
      options = options or {}
      assertOptions{options = options}

      -- make data object:
      local data = {{
         content = text,
         type  = 'text',
      }}  -- NOTE: This is not a plotly type

      -- send text request:
      return self:sendRequest{request = {
         data   = data,
         win    = win,
         eid    = env,
         opts   = options,
      }}
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
      return self:sendRequest{
         request  = ({win = win, eid = env}),
         endpoint = 'close',
      }
   end
}

return visdom.client
