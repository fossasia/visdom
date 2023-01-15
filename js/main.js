/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

/* global ACTIVE_ENV ENV_LIST $ Bin */

'use strict';

import 'fetch';
import 'rc-tree-select/assets/index.css';

import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import ReactResizeDetector from 'react-resize-detector';

import EventSystem from './EventSystem';
import Poller from './Legacy';
import EnvModal from './modals/EnvModal';
import ViewModal from './modals/ViewModal';
import TextPane from './panes/TextPane';
import {
  DEFAULT_LAYOUT,
  MARGIN,
  PANE_SIZE,
  PANES,
  ROW_HEIGHT,
} from './settings';
import ConnectionIndicator from './topbar/ConnectionIndicator';
import EnvControls from './topbar/EnvControls';
import FilterControls from './topbar/FilterControls';
import ViewControls from './topbar/ViewControls';
import WidthProvider from './Width';

const ReactGridLayout = require('react-grid-layout');
const jsonpatch = require('fast-json-patch');
const GridLayout = WidthProvider(ReactGridLayout);
const sortLayout = ReactGridLayout.utils.sortLayoutItemsByRowCol;
const getLayoutItem = ReactGridLayout.utils.getLayoutItem;

var use_envs = null;
if (ACTIVE_ENV !== '') {
  if (ACTIVE_ENV.indexOf('+') > -1) {
    // Compare case
    use_envs = ACTIVE_ENV.split('+');
  } else {
    // not compare case
    use_envs = [ACTIVE_ENV];
  }
} else {
  use_envs = JSON.parse(localStorage.getItem('envIDs')) || ['main'];
}

function App() {
  // -------------- //
  // state varibles //
  // -------------- //

  // internal variables
  const mounted = useRef(false);
  const [connected, setConnected] = useState(false);
  const [sessionInfo, setSessionInfo] = useState({ id: null, readonly: false });
  const [resizeClickHappened, setResizeClickHappened] = useState(false);
  const windowSize = useRef({
    width: 1280,
    cols: 100,
  });

  // data stores
  const [storeMeta, setStoreMeta] = useState({
    envList: ENV_LIST.slice(),
    layoutLists: new Map([['main', new Map([[DEFAULT_LAYOUT, new Map()]])]]),
  });
  const [storeData, setStoreData] = useState({
    panes: {},
    layout: [],
  });

  // user-changeable
  const [showEnvModal, setShowEnvModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [focusedPaneID, setFocusedPaneID] = useState(null);
  const [selection, setSelection] = useState({
    envIDs: use_envs,
    layoutID: DEFAULT_LAYOUT,
    // Bad form... make a copy of the global var we generated in python.
  });
  const [filterString, setFilterString] = useState(
    localStorage.getItem('filter') || ''
  );

  // non-triggering state variables
  const _bin = useRef(null);
  const _socket = useRef(null);
  const _timeoutID = useRef(null);
  const _pendingPanes = useRef([]);
  const _pendingPanesVersions = useRef({});

  // --------------------- //
  // grid helper functions //
  // --------------------- //

  // calculate number of columns based on window width
  const colWidth = () =>
    (windowSize.current.width -
      MARGIN * (windowSize.current.cols - 1) -
      MARGIN * 2) /
    windowSize.current.cols;

  // translate pixels -> RGL grid coordinates
  const p2w = (w) => (w + MARGIN) / (colWidth() + MARGIN);
  const p2h = (h) => (h + MARGIN) / (ROW_HEIGHT + MARGIN);

  // translate RGL grid width to pixels
  const w2p = (p) => p * (colWidth() + MARGIN) - MARGIN;
  const h2p = (p) => p * (ROW_HEIGHT + MARGIN) - MARGIN;

  // ---------------- //
  // helper functions //
  // ---------------- //

  // append env to pane id for localStorage key
  const keyLS = (key) => selection.envIDs[0] + '_' + key;

  // Ensure the regex filter is valid
  const getValidFilter = (filter) => {
    try {
      'test_string'.match(filter);
    } catch (e) {
      filter = '';
    }
    return filter;
  };

  // retrieve normalized window.location
  const correctPathname = () => {
    var pathname = window.location.pathname;
    if (pathname.indexOf('/env/') > -1) {
      pathname = pathname.split('/env/')[0];
    } else if (pathname.indexOf('/compare/') > -1) {
      pathname = pathname.split('/compare/')[0];
    }
    if (pathname.slice(-1) != '/') {
      pathname = pathname + '/';
    }
    return pathname;
  };

  // ------------------ //
  // batched processing //
  // ------------------ //

  // store pane to be processed
  const addPaneBatched = (pane) => {
    if (!_timeoutID.current) {
      _timeoutID.current = setTimeout(processBatchedPanes, 100);
    }
    _pendingPanes.current.push(pane);
    _pendingPanesVersions.current[
      Object.prototype.hasOwnProperty.call(pane, 'win') ? pane.win : pane.id
    ] = pane.version;
  };

  // run processing on queue
  const processBatchedPanes = () => {
    // wait until app is mounted
    if (!mounted.current) {
      _timeoutID.current = setTimeout(processBatchedPanes, 100);
      return;
    }
    let newPanes = Object.assign({}, storeData.panes);
    let newLayout = storeData.layout.slice();

    let pendingPanes = _pendingPanes.current;
    _pendingPanesVersions.current = {};
    _pendingPanes.current = [];
    pendingPanes.forEach((pane) => {
      processPane(pane, newPanes, newLayout);
    });
    _timeoutID.current = null;

    setStoreData((prev) => ({
      ...prev,
      panes: newPanes,
      layout: newLayout,
    }));
  };

  // process single pane
  const processPane = (newPane, newPanes, newLayout) => {
    // if newPane is actually window_update object, apply the to newPanes
    if (newPane.command == 'window_update') {
      newPane = jsonpatch.applyPatch(
        newPanes[newPane.win],
        newPane.content
      ).newDocument;
    }

    let exists = newPane.id in newPanes;
    newPanes[newPane.id] = newPane;

    if (!exists) {
      let stored = JSON.parse(localStorage.getItem(keyLS(newPane.id)));
      if (_bin.current == null) {
        rebin();
      }
      let paneLayout;
      if (stored) {
        paneLayout = stored;
        _bin.current.content.push(paneLayout);
      } else {
        let w = PANE_SIZE[newPane.type][0],
          h = PANE_SIZE[newPane.type][1];

        if (newPane.width) w = p2w(newPane.width);
        if (newPane.height) h = Math.ceil(p2h(newPane.height + 14));
        if (newPane.content && newPane.content.caption) h += 1;

        _bin.current.content.push({
          width: w,
          height: h,
        });

        let pos = _bin.current.position(
          newLayout.length,
          windowSize.current.cols
        );

        paneLayout = {
          i: newPane.id,
          w: w,
          h: h,
          width: w,
          height: h,
          x: pos.x,
          y: pos.y,
          static: false,
        };
      }

      newLayout.push(paneLayout);
    } else {
      let currLayout = getLayoutItem(newLayout, newPane.id);
      if (newPane.width) currLayout.w = p2w(newPane.width);
      if (newPane.height) currLayout.h = Math.ceil(p2h(newPane.height + 14));
      if (newPane.content && newPane.content.caption) currLayout.h += 1;
    }
  };

  // connect to server
  const connect = () => {
    if (_socket.current) {
      return;
    }

    const _onConnect = () => setConnected(true);
    const _onDisconnect = () => {
      // check if is mounted. error can appear on unmounted component
      if (mounted.current) {
        callbacks.current.push(() => {
          _socket.current = null;
        });
        setConnected(false);
      }
    };

    // eslint-disable-next-line no-undef
    if (USE_POLLING) {
      _socket.current = new Poller(
        correctPathname,
        _handleMessage,
        _onConnect,
        _onDisconnect
      );
      return;
    }

    var url = window.location;
    var ws_protocol = null;
    if (url.protocol == 'https:') {
      ws_protocol = 'wss';
    } else {
      ws_protocol = 'ws';
    }
    var socket = new WebSocket(
      ws_protocol + '://' + url.host + correctPathname() + 'socket'
    );

    socket.onmessage = _handleMessage;
    socket.onopen = _onConnect;
    socket.onerror = socket.onclose = _onDisconnect;
    _socket.current = socket;
  };

  // Apply patch or queries window depending on if we know of the window
  // to be processed soon and matching the expected version.
  const updateWindow = (cmd) => {
    if (
      (cmd.win in storeData.panes &&
        cmd.version == storeData.panes[cmd.win].version + 1) ||
      (cmd.win in _pendingPanesVersions.current &&
        cmd.version == _pendingPanesVersions.current[cmd.win] + 1)
    ) {
      addPaneBatched(cmd);
    } else {
      postForEnv(selection.envIDs);
    }
  };

  // handle server messages
  const _handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);
    switch (cmd.command) {
      case 'register':
        setSessionInfo((prev) => ({
          ...prev,
          id: cmd.data,
          readonly: cmd.readonly,
        }));
        break;
      case 'pane':
      case 'window':
        // If we're in compare mode and recieve an update to an environment
        // that is selected that isn't from the compare output, we need to
        // reload the compare output
        if (selection.envIDs.length > 1 && cmd.has_compare !== true) {
          postForEnv(selection.envIDs);
        } else {
          addPaneBatched(cmd);
        }
        break;
      case 'window_update':
        if (selection.envIDs.length > 1 && cmd.has_compare !== true) {
          postForEnv(selection.envIDs);
        } else {
          updateWindow(cmd);
        }
        break;
      case 'reload':
        for (var it in cmd.data) {
          localStorage.setItem(keyLS(it), JSON.stringify(cmd.data[it]));
        }
        break;
      case 'close':
        closePane(cmd.data);
        break;
      case 'layout':
        relayout();
        break;
      case 'env_update':
        var layoutLists = storeMeta.layoutLists;
        for (var envIdx in cmd.data) {
          if (!layoutLists.has(cmd.data[envIdx])) {
            layoutLists.set(
              cmd.data[envIdx],
              new Map([[DEFAULT_LAYOUT, new Map()]])
            );
          }
        }
        setStoreMeta((prev) => ({
          ...prev,
          envList: cmd.data,
          layoutLists: layoutLists,
        }));
        break;
      case 'layout_update':
        parseLayoutsFromServer(cmd.data);
        break;
      default:
        console.error('unrecognized command', cmd);
    }
  };

  // we need to update the socket-callback so that we have an up-to date state
  if (_socket.current) _socket.current.onmessage = _handleMessage;

  // close server connection
  const disconnect = () => {
    _socket.current.close();
    _socket.current = null;
  };

  // send message to server
  const sendSocketMessage = (data) => {
    if (!_socket.current) {
      // TODO: error? warn?
      return;
    }

    let msg = JSON.stringify(data);
    return _socket.current.send(msg);
  };

  // remove paneID from pane list
  // (also tell server)
  const closePane = (paneID, keepPosition = false, setState = true) => {
    if (sessionInfo.readonly) {
      return;
    }
    let newPanes = Object.assign({}, storeData.panes);
    delete newPanes[paneID];
    if (!keepPosition) {
      localStorage.removeItem(keyLS(paneID));

      sendSocketMessage({
        cmd: 'close',
        data: paneID,
        eid: selection.envIDs[0],
      });
    }

    if (setState) {
      // Make sure we remove the pane from our layout.
      let newLayout = storeData.layout.filter(
        (paneLayout) => paneLayout.i !== paneID
      );

      setStoreData((prev) => ({
        ...prev,
        layout: newLayout,
        panes: newPanes,
      }));
      setFocusedPaneID(focusedPaneID === paneID ? null : focusedPaneID);
      callbacks.current.push('relayout');
    }
  };

  const closeAllPanes = () => {
    if (sessionInfo.readonly) {
      return;
    }
    Object.keys(storeData.panes).map((paneID) => {
      closePane(paneID, false, false);
    });
    rebin();
    setStoreData((prev) => ({
      ...prev,
      layout: [],
      panes: {},
    }));
    setFocusedPaneID(null);
  };

  const onEnvSelect = (selectedNodes) => {
    var isSameEnv = selectedNodes.length == selection.envIDs.length;
    if (isSameEnv) {
      for (var i = 0; i < selectedNodes.length; i++) {
        if (selectedNodes[i] != selection.envIDs[i]) {
          isSameEnv = false;
          break;
        }
      }
    }
    setSelection((prev) => ({
      ...prev,
      envIDs: selectedNodes,
    }));
    setStoreData((prev) => ({
      ...prev,
      panes: isSameEnv ? storeData.panes : {},
      layout: isSameEnv ? storeData.layout : [],
    }));
    setFocusedPaneID(isSameEnv ? focusedPaneID : null);
    localStorage.setItem('envIDs', JSON.stringify(selectedNodes));
    postForEnv(selectedNodes);
  };

  const postForEnv = (envIDs) => {
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    if (envIDs.length == 1) {
      $.post(
        correctPathname() + 'env/' + envIDs[0],
        JSON.stringify({
          sid: sessionInfo.id,
        })
      );
    } else if (envIDs.length > 1) {
      $.post(
        correctPathname() + 'compare/' + envIDs.join('+'),
        JSON.stringify({
          sid: sessionInfo.id,
        })
      );
    }
  };

  const onEnvDelete = (env2delete, previousEnv) => {
    sendSocketMessage({
      cmd: 'delete_env',
      prev_eid: previousEnv,
      eid: env2delete,
    });
  };

  const onEnvSave = (env) => {
    if (!connected) {
      return;
    }

    updateLayout(storeData.layout);

    let payload = {};
    Object.keys(storeData.panes).map((paneID) => {
      payload[paneID] = JSON.parse(localStorage.getItem(keyLS(paneID)));
    });

    sendSocketMessage({
      cmd: 'save',
      data: payload,
      prev_eid: selection.envIDs[0],
      eid: env,
    });

    let newEnvList = storeMeta.envList;
    if (newEnvList.indexOf(env) === -1) {
      newEnvList.push(env);
    }
    let layoutLists = storeMeta.layoutLists;

    for (var envIdx in newEnvList) {
      if (!layoutLists.has(newEnvList[envIdx])) {
        layoutLists.set(
          newEnvList[envIdx],
          new Map([[DEFAULT_LAYOUT, new Map()]])
        );
      }
    }

    setStoreMeta((prev) => ({
      ...prev,
      envList: newEnvList,
      layoutLists: layoutLists,
    }));
    setSelection((prev) => ({
      ...prev,
      envIDs: [env],
    }));
  };

  const focusPane = (paneID, callback) => {
    if (focusedPaneID != paneID) {
      setFocusedPaneID(paneID);
      if (callback) callbacks.current.push(callback);
    } else if (callback) callback();
  };

  const blurPane = () => {
    if (focusedPaneID != null) setFocusedPaneID(null);
  };

  const resizePane = (layout, oldLayoutItem, layoutItem) => {
    // register a double click on the resize handle to reset the window size
    if (
      resizeClickHappened &&
      layoutItem.w == oldLayoutItem.w &&
      layoutItem.h == oldLayoutItem.h
    ) {
      let pane = storeData.panes[layoutItem.i];

      // resets to default layout (same as during pane creation)
      layoutItem.w = pane.width ? p2w(pane.width) : PANE_SIZE[pane.type][0];
      layoutItem.h = pane.height
        ? Math.ceil(p2h(pane.height + 14))
        : PANE_SIZE[pane.type][1];
      if (pane.content && pane.content.caption) layoutItem.h += 1;
    }

    // update layout according to user interaction
    setSelection((prev) => ({
      ...prev,
      layoutID: DEFAULT_LAYOUT,
    }));
    focusPane(layoutItem.i);
    updateLayout(layout);
    sendLayoutItemState(layoutItem);

    // register a double click in this function
    setResizeClickHappened(true);
    setTimeout(
      function () {
        setResizeClickHappened(false);
      }.bind(this),
      400
    );
  };

  const movePane = (layout) => {
    setSelection((prev) => ({
      ...prev,
      layoutID: DEFAULT_LAYOUT,
    }));
    updateLayout(layout);
  };

  const rebin = (layout) => {
    layout = layout ? layout : storeData.layout;
    let layoutID = selection.layoutID;
    if (layoutID !== DEFAULT_LAYOUT) {
      let envLayoutList = getCurrLayoutList();
      let layoutMap = envLayoutList.get(selection.layoutID);
      layout = layout.map((paneLayout) => {
        if (layoutMap.has(paneLayout.i)) {
          let storedVals = layoutMap.get(paneLayout.i);
          paneLayout.h = storedVals[1];
          paneLayout.height = storedVals[1];
          paneLayout.w = storedVals[2];
          paneLayout.width = storedVals[2];
        }
        return paneLayout;
      });
    }
    let contents = layout.map((paneLayout) => {
      return {
        width: paneLayout.w,
        height: paneLayout.h,
      };
    });

    _bin.current = new Bin.ShelfFirst(contents, windowSize.current.cols);
    return layout;
  };

  const getCurrLayoutList = () => {
    if (storeMeta.layoutLists.has(selection.envIDs[0])) {
      return storeMeta.layoutLists.get(selection.envIDs[0]);
    } else {
      return new Map();
    }
  };

  const relayout = () => {
    let layout = rebin();

    let sorted = sortLayout(layout);
    let newPanes = Object.assign({}, storeData.panes);
    let filter = getValidFilter(filterString);
    let old_sorted = sorted.slice();
    let layoutID = selection.layoutID;
    let envLayoutList = getCurrLayoutList();
    let layoutMap = envLayoutList.get(selection.layoutID);
    // Sort out things that were filtered away
    sorted = sorted.sort(function (a, b) {
      let diff =
        (newPanes[a.i].title.match(filter) != null) -
        (newPanes[b.i].title.match(filter) != null);
      if (diff != 0) {
        return -diff;
      } else if (layoutID !== DEFAULT_LAYOUT) {
        let aVal = layoutMap.has(a.i) ? -layoutMap.get(a.i)[0] : 1;
        let bVal = layoutMap.has(b.i) ? -layoutMap.get(b.i)[0] : 1;
        let diff = bVal - aVal;
        if (diff != 0) {
          // At least one of the two was in the layout map.
          return diff;
        }
      }
      return old_sorted.indexOf(a) - old_sorted.indexOf(b); // stable sort
    });

    let newLayout = sorted.map((paneLayout, idx) => {
      let pos = _bin.current.position(idx, windowSize.current.cols);

      newPanes[paneLayout.i].i = idx;

      return Object.assign({}, paneLayout, pos);
    });

    setStoreData((prev) => ({
      ...prev,
      panes: newPanes,
    }));
    updateLayout(newLayout);
  };

  const toggleOnlineState = () => {
    if (connected) {
      disconnect();
    } else {
      connect();
    }
  };

  const updateLayout = (layout) => {
    setStoreData((prev) => ({ ...prev, layout: layout }));
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    storeData.layout = layout;
  };
  useEffect(() => {
    storeData.layout.map((playout) => {
      localStorage.setItem(keyLS(playout.i), JSON.stringify(playout));
    });
  }, [storeData]);

  /**
   * Send layout item state to backend to update backend state.
   *
   * @param layout Layout to be sent to backend.
   */
  const sendLayoutItemState = ({
    i,
    h,
    w,
    x,
    y,
    moved,
    static: staticBool,
  }) => {
    sendSocketMessage({
      cmd: 'layout_item_update',
      eid: selection.envIDs[0],
      win: i,
      data: { i, h, w, x, y, moved, static: staticBool },
    });
  };

  const updateToLayout = (newLayoutID) => {
    setSelection((prev) => ({
      ...prev,
      layoutID: newLayoutID,
    }));
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    selection.layoutID = newLayoutID;
    if (selection.layoutID !== DEFAULT_LAYOUT) {
      callbacks.current.push('relayout');
      callbacks.current.push('relayout');
      callbacks.current.push('relayout');
    }
  };

  const parseLayoutsFromServer = (layoutJSON) => {
    // Handles syncing layout state from the server
    if (layoutJSON.length == 0) {
      return; // Skip totally blank updates, these are empty inits
    }
    let layoutsObj = JSON.parse(layoutJSON);
    let layoutLists = new Map();
    for (let envName of Object.keys(layoutsObj)) {
      let layoutList = new Map();
      for (let layoutName of Object.keys(layoutsObj[envName])) {
        let layoutMap = new Map();
        for (let contentID of Object.keys(layoutsObj[envName][layoutName])) {
          layoutMap.set(contentID, layoutsObj[envName][layoutName][contentID]);
        }
        layoutList.set(layoutName, layoutMap);
      }
      layoutLists.set(envName, layoutList);
    }
    let currList = getCurrLayoutList();
    let layoutID = selection.layoutID;
    if (!currList.has(selection.layoutID)) {
      // If the current view was deleted by someone else (eek)
      layoutID = DEFAULT_LAYOUT;
    }
    setStoreMeta((prev) => ({
      ...prev,
      layoutLists: layoutLists,
    }));
    setSelection((prev) => ({
      ...prev,
      layoutID: layoutID,
    }));
  };

  const publishEvent = (event) => {
    EventSystem.publish('global.event', event);
  };

  /**
   * Send message to backend.
   *
   * The `data` object is extended by pane and environment Id.
   * This function is exposed to Pane components through `appApi` prop.
   * Note: Only focused panes should call this method.
   *
   * @param data Data to be sent to backend.
   */
  const sendPaneMessage = (data, target = null) => {
    if (!target) target = focusedPaneID;
    if (target === null || sessionInfo.readonly) {
      return;
    }
    let finalData = {
      target: target,
      eid: selection.envIDs[0],
    };
    $.extend(finalData, data);
    sendSocketMessage({
      cmd: 'forward_to_vis',
      data: finalData,
    });
  };

  const sendEmbeddingPop = (data) => {
    if (focusedPaneID === null || sessionInfo.readonly) {
      return;
    }
    let finalData = {
      target: focusedPaneID,
      eid: selection.envIDs[0],
    };
    $.extend(finalData, data);
    sendSocketMessage({
      cmd: 'pop_embeddings_pane',
      data: finalData,
    });
  };

  const exportLayoutsToServer = (layoutLists) => {
    // pushes layouts to the server
    let objForm = {};
    for (let [envName, layoutList] of layoutLists) {
      objForm[envName] = {};
      for (let [layoutName, layoutMap] of layoutList) {
        objForm[envName][layoutName] = {};
        for (let [contentID, contentLoc] of layoutMap) {
          objForm[envName][layoutName][contentID] = contentLoc;
        }
      }
    }
    let exportForm = JSON.stringify(objForm);
    sendSocketMessage({
      cmd: 'save_layouts',
      data: exportForm,
    });
  };

  const onLayoutSave = (layoutName) => {
    // Saves the current view as a new layout, pushes to the server
    let sorted = sortLayout(storeData.layout);
    let layoutMap = new Map();
    for (var idx = 0; idx < sorted.length; idx++) {
      let pane = storeData.panes[sorted[idx].i];
      let currLayout = getLayoutItem(storeData.layout, pane.id);
      layoutMap.set(sorted[idx].i, [idx, currLayout.h, currLayout.w]);
    }
    let layoutLists = storeMeta.layoutLists;
    layoutLists.get(selection.envIDs[0]).set(layoutName, layoutMap);
    exportLayoutsToServer(layoutLists);
    setStoreMeta((prev) => ({
      ...prev,
      layoutLists: layoutLists,
    }));
    setSelection((prev) => ({
      ...prev,
      layoutID: layoutName,
    }));
  };

  const onLayoutDelete = (layoutName) => {
    // Deletes the selected view, pushes to server
    let layoutLists = storeMeta.layoutLists;
    layoutLists.get(selection.envIDs[0]).delete(layoutName);
    exportLayoutsToServer(layoutLists);
    setStoreMeta((prev) => ({
      ...prev,
      layoutLists: layoutLists,
    }));
    setSelection((prev) => ({
      ...prev,
      layoutID: layoutLists.get(selection.envIDs[0]).keys()[0],
    }));
  };

  // -------
  // effects
  // -------

  // flush pre-render callbacks
  const callbacks = useRef([]);
  callbacks.current.forEach((cb) => {
    if (cb === 'relayout') relayout();
    else if (cb) cb();
  });
  callbacks.current = [];

  // ask server for envs after registration succeeded
  useEffect(() => {
    postForEnv(selection.envIDs);
  }, [sessionInfo]);

  // connect session upon componentDidMount
  useEffect(connect, []);

  //componentDidUpdate
  useEffect(() => {
    if (mounted.current) {
      if (selection.envIDs.length > 0) {
        postForEnv(selection.envIDs);
      } else {
        setSelection((prev) => ({
          ...prev,
          envIDs: ['main'],
        }));
        postForEnv(['main']);
      }
    }

    // Bootstrap tooltips need some encouragement
    $('#clear-button').attr('data-original-title', 'Clear Current Environment');
  }, [mounted.current]);

  // define what mounted means for this app:
  // 1. WidthProvider knows the correct windowSize
  // 2. We have a connection to the server
  useEffect(() => {
    if (windowSize.current.width <= 0 && windowSize.current.cols <= 0) return;
    if (!sessionInfo.id) return;
    mounted.current = true;
    relayout();
  }, [windowSize.current, sessionInfo]);

  // on filter change, ping all panes to force redraw
  useEffect(() => {
    Object.keys(storeData.panes).map((paneID) => {
      focusPane(paneID);
    });
    localStorage.setItem('filter', filterString);
  }, [filterString]);

  const onWidthChange = (width, cols) => {
    windowSize.current.cols = cols;
    windowSize.current.width = width;
  };

  let panes = Object.keys(storeData.panes).map((id) => {
    let pane = storeData.panes[id];

    try {
      let Comp = PANES[pane.type];
      if (!Comp) {
        throw new Error('unrecognized pane type: ' + pane);
      }
      let panelayout = getLayoutItem(storeData.layout, id);
      let filter = getValidFilter(filterString);
      let isVisible = pane.title.match(filter);

      const PANE_TITLE_BAR_HEIGHT = 14;

      var _height = Math.round(h2p(panelayout.h));
      var _width = Math.round(w2p(panelayout.w));

      return (
        <div key={pane.id} className={isVisible ? '' : 'hidden-window'}>
          <ReactResizeDetector handleWidth handleHeight>
            <Comp
              {...pane}
              key={pane.id}
              onClose={closePane}
              onFocus={focusPane}
              isFocused={pane.id === focusedPaneID}
              w={panelayout.w}
              h={panelayout.h}
              width={w2p(panelayout.w)}
              height={h2p(panelayout.h) - PANE_TITLE_BAR_HEIGHT}
              _width={_width}
              _height={_height - PANE_TITLE_BAR_HEIGHT}
              appApi={{
                sendPaneMessage: sendPaneMessage,
                sendEmbeddingPop: sendEmbeddingPop,
              }}
            />
          </ReactResizeDetector>
        </div>
      );
    } catch (err) {
      return (
        <div key={pane.id}>
          <TextPane
            content={
              'Error: ' +
              (err.message ||
                JSON.stringify(err, Object.getOwnPropertyNames(err)))
            }
            id={pane.id}
            key={pane.id}
            onClose={closePane}
            onFocus={focusPane}
            isFocused={pane.id === focusedPaneID}
            w={300}
            h={300}
            appApi={{ sendPaneMessage: sendPaneMessage }}
          />
        </div>
      );
    }
  });

  let modals = [
    <EnvModal
      key="EnvModal"
      activeEnv={selection.envIDs[0]}
      connected={connected}
      envList={storeMeta.envList}
      onEnvDelete={onEnvDelete}
      onEnvSave={onEnvSave}
      onModalClose={() => setShowEnvModal(false)}
      show={showEnvModal}
    />,
    <ViewModal
      key="ViewModal"
      activeLayout={selection.layoutID}
      connected={connected}
      layoutList={getCurrLayoutList()}
      onModalClose={() => setShowViewModal(false)}
      onLayoutDelete={onLayoutDelete.bind(this)}
      onLayoutSave={onLayoutSave.bind(this)}
      show={showViewModal}
    />,
  ];

  let envControls = (
    <EnvControls
      connected={connected}
      envIDs={selection.envIDs}
      envList={storeMeta.envList}
      envSelectorStyle={{
        width: Math.max(window.innerWidth / 3, 50),
      }}
      onEnvClear={closeAllPanes}
      onEnvManageButton={() => setShowEnvModal(!showEnvModal)}
      onEnvSelect={onEnvSelect}
      readonly={sessionInfo.readonly}
    />
  );
  let viewControls = (
    <ViewControls
      activeLayout={selection.layoutID}
      connected={connected}
      envIDs={selection.envIDs}
      layoutList={getCurrLayoutList()}
      onRepackButton={() => {
        relayout();
        relayout();
      }}
      onViewChange={updateToLayout}
      onViewManageButton={() => setShowViewModal(!showViewModal)}
      readonly={sessionInfo.readonly}
    />
  );
  let filterControl = (
    <FilterControls
      filter={filterString}
      onFilterChange={(ev) => {
        setFilterString(ev.target.value);
        callbacks.current.push('relayout');
      }}
      onFilterClear={() => {
        setFilterString('');
        callbacks.current.push('relayout');
      }}
    />
  );
  let connectionIndicator = (
    <ConnectionIndicator
      connected={connected}
      onClick={toggleOnlineState}
      readonly={sessionInfo.readonly}
    />
  );

  return (
    <div>
      {modals}
      <div className="navbar-form navbar-default">
        <span className="navbar-brand visdom-title">visdom</span>
        <span className="vertical-line" />
        &nbsp;&nbsp;
        {envControls}
        &nbsp;&nbsp;
        <span className="vertical-line" />
        &nbsp;&nbsp;
        {viewControls}
        <span
          style={{
            float: 'right',
          }}
        >
          {filterControl}
          &nbsp;&nbsp;
          {connectionIndicator}
        </span>
      </div>
      <div
        tabIndex="-1"
        role="presentation"
        className="no-focus"
        onBlur={blurPane}
        onClick={publishEvent}
        onKeyUp={publishEvent}
        onKeyDown={publishEvent}
        onKeyPress={publishEvent}
      >
        <GridLayout
          className="layout"
          rowHeight={ROW_HEIGHT}
          autoSize={false}
          margin={[MARGIN, MARGIN]}
          layout={storeData.layout}
          draggableHandle={'.bar'}
          onWidthChange={onWidthChange}
          onResizeStop={resizePane}
          onDragStop={movePane}
        >
          {panes}
        </GridLayout>
      </div>
    </div>
  );
}

function load() {
  ReactDOM.render(<App />, document.getElementById('app'));
  document.removeEventListener('DOMContentLoaded', load);
}

document.addEventListener('DOMContentLoaded', load);

$(document).ready(function () {
  $('[data-toggle="tooltip"]').tooltip({
    container: 'body',
    delay: {
      show: 600,
      hide: 100,
    },
    trigger: 'hover',
  });
});
