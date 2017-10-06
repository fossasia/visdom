--[[

Copyright 2017-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the license found in the
LICENSE file in the root directory of this source tree.

]]--

-- load torchnet:
require 'torch'
local tnt = require 'torchnet'

-- intialize visdom Torch client:
local visdom = require 'visdom'
local plot = visdom{server = 'http://localhost', port = 8097}

-- use GPU or not:
local cmd = torch.CmdLine()
cmd:option('-usegpu', false, 'use gpu for training')
local config = cmd:parse(arg)
print(string.format('| running on %s...', config.usegpu and 'GPU' or 'CPU'))

-- function that creates a dataset iterator:
local function getIterator(mode, batchsize)

   -- load MNIST dataset:
   local mnist = require 'mnist'
   local dataset = mnist[mode .. 'dataset']()
   dataset.data = dataset.data:reshape(dataset.data:size(1),
      dataset.data:size(2) * dataset.data:size(3)):double():div(256)

   -- return dataset iterator:
   return tnt.DatasetIterator{
      dataset = tnt.BatchDataset{
         batchsize = 128,
         dataset = tnt.ListDataset{
            list = torch.range(1, dataset.data:size(1)):long(),
            load = function(idx)
               return {
                  input  = dataset.data[idx],
                  target = torch.LongTensor{dataset.label[idx] + 1},
               }  -- sample contains input and target
            end,
         }
      }
   }
end

-- get data iterators:
local maxepoch = 10
local trainiterator = getIterator('train')
local testiterator  = getIterator('test')
local trainsize = trainiterator:exec('size')
local  testsize =  testiterator:exec('size')

-- set up logistic regressor:
local net = nn.Sequential():add(nn.Linear(784, 10))
local criterion = nn.CrossEntropyCriterion()

-- set up training engine and meters:
local engine = tnt.SGDEngine()
local meter  = tnt.AverageValueMeter()
local clerr  = tnt.ClassErrorMeter{topk = {1}}

-- reset meters at start of epoch:
local epoch = 0
engine.hooks.onStartEpoch = function(state)
   epoch = epoch + 1
   print(string.format('| epoch %d of %d...', epoch, maxepoch))
   meter:reset()
   clerr:reset()
end

-- compute and plot training loss / error:
local trainlosshandle, trainerrhandle
local trainlosshist = torch.DoubleTensor(trainsize * maxepoch):fill(0)
local trainerrhist  = torch.DoubleTensor(trainsize * maxepoch):fill(0)
local testlosshist  = torch.DoubleTensor(maxepoch):fill(0)
local testerrhist   = torch.DoubleTensor(maxepoch):fill(0)
engine.hooks.onForwardCriterion = function(state)

   -- update meters:
   meter:add(state.criterion.output)
   clerr:add(state.network.output, state.sample.target)

   -- update loss / error history:
   local idx = state.training and (state.t + 1) or epoch
   local losshist = state.training and trainlosshist or testlosshist
   local errhist  = state.training and trainerrhist  or testerrhist
   losshist[idx] = meter:value()
   errhist[ idx] = clerr:value{k = 1}

   -- you need at least two points to draw a line:
   if state.training and state.t >= 1 then

      -- plot training loss:
      trainlosshandle = plot:line{
         Y   = trainlosshist:narrow(1, 1, state.t + 1),
         X   = torch.range(1, state.t + 1),
         win = trainlosshandle,  -- keep handles around so we can update plot
         opts = {
            markers = false,
            title   = 'Training loss',
            xlabel  = 'Batch number',
            ylabel  = 'Loss value',
         },
      }  -- create new plot if it does not yet exist, otherwise, update plot

      -- plot training error:
      trainerrhandle = plot:line{
         Y   = trainerrhist:narrow(1, 1, state.t + 1),
         X   = torch.range(1, state.t + 1),
         win = trainerrhandle,  -- keep handles around so we can update plot
         opts = {
            markers = false,
            title   = 'Training error',
            xlabel  = 'Batch number',
            ylabel  = 'Classification error',
         },
      }  -- create new plot if it does not yet exist, otherwise, update plot
   end
end

-- compute test loss at end of epoch:
local testlosshandle, testerrhandle
engine.hooks.onEndEpoch = function(state)

   -- measure test error:
   meter:reset()
   clerr:reset()
   engine:test{
      network   = net,
      iterator  = testiterator,
      criterion = criterion,
   }

   -- you need at least two points to draw a line:
   if epoch >= 2 then

      -- plot test loss:
      testlosshandle = plot:line{
         Y   = testlosshist:narrow(1, 1, state.epoch),
         X   = torch.range(1, state.epoch),
         win = testlosshandle,  -- keep handles around so we can update plot
         opts = {
            markers = false,
            title   = 'Test loss',
            xlabel  = 'Epoch',
            ylabel  = 'Loss value',
         }
      }  -- create new plot if it does not yet exist, otherwise, update plot

      -- plot test error:
      testerrhandle = plot:line{
         Y   = testerrhist:narrow(1, 1, state.epoch),
         X   = torch.range(1, state.epoch),
         win = testerrhandle,  -- keep handles around so we can update plot
         opts = {
            markers = false,
            title   = 'Test error',
            xlabel  = 'Epoch',
            ylabel  = 'Classification error',
         }
      }  -- create new plot if it does not yet exist, otherwise, update plot
   end
end

-- set up GPU training:
if config.usegpu then

   -- copy model to GPU:
   require 'cunn'
   net       = net:cuda()
   criterion = criterion:cuda()

   -- copy sample to GPU buffer:
   local igpu, tgpu = torch.CudaTensor(), torch.CudaTensor()
   engine.hooks.onSample = function(state)
      igpu:resize(state.sample.input:size() ):copy(state.sample.input)
      tgpu:resize(state.sample.target:size()):copy(state.sample.target)
      state.sample.input  = igpu
      state.sample.target = tgpu
   end  -- alternatively, this logic can be implemented via a TransformDataset
end

-- train the model:
engine:train{
   network   = net,
   iterator  = trainiterator,
   criterion = criterion,
   lr        = 0.2,
   maxepoch  = maxepoch,
}
print('| done.')
