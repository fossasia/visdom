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

import React from 'react';
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
const md5 = require('md5');
const stringify = require('json-stable-stringify');
const GridLayout = WidthProvider(ReactGridLayout);
const sortLayout = ReactGridLayout.utils.sortLayoutItemsByRowCol;
const getLayoutItem = ReactGridLayout.utils.getLayoutItem;

var use_env = null;
var use_envs = null;
if (ACTIVE_ENV !== '') {
  if (ACTIVE_ENV.indexOf('+') > -1) {
    // Compare case
    use_env = null;
    use_envs = ACTIVE_ENV.split('+');
  } else {
    // not compare case
    use_env = ACTIVE_ENV;
    use_envs = [ACTIVE_ENV];
  }
} else {
  use_env = localStorage.getItem('envID') || 'main';
  use_envs = JSON.parse(localStorage.getItem('envIDs')) || ['main'];
}

// TODO: Move some of this to smaller components and/or use something like redux
// to move state out of the app to a standalone store.
class App extends React.Component {
  state = {
    connected: false,
    readonly: false,
    sessionID: null,
    panes: {},
    consistent_pane_copy: {},
    focusedPaneID: null,
    envID: use_env,
    envIDs: use_envs,
    layoutID: DEFAULT_LAYOUT,
    // Bad form... make a copy of the global var we generated in python.
    envList: ENV_LIST.slice(),
    filter: localStorage.getItem('filter') || '',
    layout: [],
    cols: 100,
    width: 1280,
    layoutLists: new Map([['main', new Map([[DEFAULT_LAYOUT, new Map()]])]]),
    showEnvModal: false,
    showViewModal: false,
    envSelectorStyle: {
      width: 1280 / 2,
    },
  };

  _bin = null;
  _socket = null;
  _timeoutID = null;
  _pendingPanes = [];
  _firstLoad = true;

  constructor() {
    super();
    this.updateDimensions = this.updateDimensions.bind(this);
    this.resize_click_happened = false;
  }

  colWidth = () => {
    return (
      (this.state.width - MARGIN * (this.state.cols - 1) - MARGIN * 2) /
      this.state.cols
    );
  };

  p2w = (w) => {
    // translate pixels -> RGL grid coordinates
    let colWidth = this.colWidth();
    return (w + MARGIN) / (colWidth + MARGIN);
  };

  w2p = (p) => {
    let colWidth = this.colWidth();
    return p * (colWidth + MARGIN) - MARGIN;
  };

  p2h = (h) => {
    return (h + MARGIN) / (ROW_HEIGHT + MARGIN);
  };

  h2p = (p) => {
    return p * (ROW_HEIGHT + MARGIN) - MARGIN;
  };

  keyLS = (key) => {
    // append env to pane id for localStorage key
    return this.state.envID + '_' + key;
  };

  getValidFilter = (filter) => {
    // Ensure the regex filter is valid
    try {
      'test_string'.match(filter);
    } catch (e) {
      filter = '';
    }
    return filter;
  };

  correctPathname = () => {
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

  addPaneBatched = (pane) => {
    if (!this._timeoutID) {
      this._timeoutID = setTimeout(this.processBatchedPanes, 100);
    }
    this._pendingPanes.push(pane);
  };

  processBatchedPanes = () => {
    let newPanes = Object.assign({}, this.state.panes);
    let newLayout = this.state.layout.slice();

    this._pendingPanes.forEach((pane) => {
      this.processPane(pane, newPanes, newLayout);
    });

    this._pendingPanes = [];
    this._timeoutID = null;

    this.setState({
      panes: newPanes,
      layout: newLayout,
    });
  };

  processPane = (newPane, newPanes, newLayout) => {
    let exists = newPane.id in newPanes;
    newPanes[newPane.id] = newPane;

    if (!exists) {
      this.state.consistent_pane_copy[newPane.id] = JSON.parse(
        JSON.stringify(newPane)
      ); //Deep Copy
      let stored = JSON.parse(localStorage.getItem(this.keyLS(newPane.id)));
      if (this._bin == null) {
        this.rebin();
      }
      if (stored) {
        var paneLayout = stored;
        this._bin.content.push(paneLayout);
      } else {
        let w = PANE_SIZE[newPane.type][0],
          h = PANE_SIZE[newPane.type][1];

        if (newPane.width) w = this.p2w(newPane.width);
        if (newPane.height) h = Math.ceil(this.p2h(newPane.height + 14));
        if (newPane.content && newPane.content.caption) h += 1;

        this._bin.content.push({
          width: w,
          height: h,
        });

        let pos = this._bin.position(newLayout.length, this.state.cols);

        var paneLayout = {
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
      if (newPane.width) currLayout.w = this.p2w(newPane.width);
      if (newPane.height)
        currLayout.h = Math.ceil(this.p2h(newPane.height + 14));
      if (newPane.content && newPane.content.caption) currLayout.h += 1;
      this.state.consistent_pane_copy[newPane.id] = JSON.parse(
        JSON.stringify(newPane)
      ); //Deep Copy
    }
  };

  connect = () => {
    if (this._socket) {
      return;
    }
    // eslint-disable-next-line no-undef
    if (USE_POLLING) {
      this._socket = new Poller(this);
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
      ws_protocol + '://' + url.host + this.correctPathname() + 'socket'
    );

    socket.onmessage = this._handleMessage;

    socket.onopen = () => {
      this.setState({
        connected: true,
      });
    };

    socket.onerror = socket.onclose = () => {
      this.setState({ connected: false }, function () {
        this._socket = null;
      });
    };

    this._socket = socket;
  };

  _checkWindow = (cmd, numTries) => {
    if (cmd.win in this.state.consistent_pane_copy) {
      // Apply patch and check hash. Re-fetch if final window doesn't match hash
      let windowContent = this.state.consistent_pane_copy[cmd.win];
      let finalWindow = jsonpatch.applyPatch(
        windowContent,
        cmd.content
      ).newDocument;
      let hashed = md5(stringify(finalWindow));
      if (hashed === cmd.finalHash) {
        this.state.consistent_pane_copy[cmd.win] = finalWindow;
        let modifiedWindow = this.state.panes[cmd.win];
        let modifiedFinalWindow = jsonpatch.applyPatch(
          modifiedWindow,
          cmd.content
        ).newDocument;
        this.addPaneBatched(modifiedFinalWindow);
      } else {
        this.postForEnv(this.state.envIDs);
      }
    } else {
      numTries--;
      if (numTries) {
        setTimeout(this._checkWindow, 100, cmd, numTries);
      } else {
        this.postForEnv(this.state.envIDs);
      }
    }
  };

  _handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);
    switch (cmd.command) {
      case 'register':
        this.setState(
          {
            sessionID: cmd.data,
            readonly: cmd.readonly,
          },
          () => {
            this.postForEnv(this.state.envIDs);
          }
        );
        break;
      case 'pane':
      case 'window':
        // If we're in compare mode and recieve an update to an environment
        // that is selected that isn't from the compare output, we need to
        // reload the compare output
        if(cmd.envID !== undefined && cmd.envID !== this.state.envID){
          // If env of the window is not same to the current env then ignore it
          break;
        }
        if(cmd.contentID === 'compare_legend' && this.state.envIDs.length < 2){
          // if compare_legend comes and only one env is selected then ignore it
          break;
        }
        if (this.state.envIDs.length > 1 && cmd.has_compare !== true) {
          this.postForEnv(this.state.envIDs);
        } else {
          this.addPaneBatched(cmd);
        }
        break;
      case 'window_update':
        if (this.state.envIDs.length > 1 && cmd.has_compare !== true) {
          this.postForEnv(this.state.envIDs);
        } else {
          let numTries = 3;
          // Check to see if the window exists before trying to update
          setTimeout(this._checkWindow, 0, cmd, numTries);
        }
        break;
      case 'reload':
        for (var it in cmd.data) {
          localStorage.setItem(this.keyLS(it), JSON.stringify(cmd.data[it]));
        }
        break;
      case 'close':
        this.closePane(cmd.data);
        break;
      case 'layout':
        this.relayout();
        break;
      case 'env_update':
        var layoutLists = this.state.layoutLists;
        for (var envIdx in cmd.data) {
          if (!layoutLists.has(cmd.data[envIdx])) {
            layoutLists.set(
              cmd.data[envIdx],
              new Map([[DEFAULT_LAYOUT, new Map()]])
            );
          }
        }
        this.setState({
          envList: cmd.data,
          layoutLists: layoutLists,
        });
        break;
      case 'layout_update':
        this.parseLayoutsFromServer(cmd.data);
        break;
      default:
        console.error('unrecognized command', cmd);
    }
  };

  disconnect = () => {
    this._socket.close();
  };

  sendSocketMessage(data) {
    if (!this._socket) {
      // TODO: error? warn?
      return;
    }

    let msg = JSON.stringify(data);
    return this._socket.send(msg);
  }

  closePane = (paneID, keepPosition = false, setState = true) => {
    if (this.state.readonly) {
      return;
    }
    let newPanes = Object.assign({}, this.state.panes);
    let newPanesCopy = Object.assign({}, this.state.consistent_pane_copy);
    delete newPanes[paneID];
    delete newPanesCopy[paneID];
    if (!keepPosition) {
      localStorage.removeItem(this.keyLS(this.id));

      this.sendSocketMessage({
        cmd: 'close',
        data: paneID,
        eid: this.state.envID,
      });
    }

    if (setState) {
      let focusedPaneID = this.state.focusedPaneID;
      // Make sure we remove the pane from our layout.
      let newLayout = this.state.layout.filter(
        (paneLayout) => paneLayout.i !== paneID
      );

      this.setState(
        {
          layout: newLayout,
          panes: newPanes,
          consistent_pane_copy: newPanesCopy,
          focusedPaneID: focusedPaneID === paneID ? null : focusedPaneID,
        },
        () => {
          this.relayout();
        }
      );
    }
  };

  closeAllPanes = () => {
    if (this.state.readonly) {
      return;
    }
    Object.keys(this.state.panes).map((paneID) => {
      this.closePane(paneID, false, false);
    });
    this.rebin();
    this.setState({
      layout: [],
      panes: {},
      consistent_pane_copy: {},
      focusedPaneID: null,
      // confirmClear: false,
    });
  };

  onEnvSelect = (selectedNodes) => {
    var isSameEnv = selectedNodes.length == this.state.envIDs.length;
    if (isSameEnv) {
      for (var i = 0; i < selectedNodes.length; i++) {
        if (selectedNodes[i] != this.state.envIDs[i]) {
          isSameEnv = false;
          break;
        }
      }
    }
    var envID = null;
    if (selectedNodes.length == 1) {
      envID = selectedNodes[0];
    }
    this.setState({
      envID: envID,
      envIDs: selectedNodes,
      panes: isSameEnv ? this.state.panes : {},
      layout: isSameEnv ? this.state.layout : [],
      focusedPaneID: isSameEnv ? this.state.focusedPaneID : null,
    });
    localStorage.setItem('envID', envID);
    localStorage.setItem('envIDs', JSON.stringify(selectedNodes));
    this.postForEnv(selectedNodes);
  };

  postForEnv = (envIDs) => {
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    if (envIDs.length == 1) {
      $.post(
        this.correctPathname() + 'env/' + envIDs[0],
        JSON.stringify({
          sid: this.state.sessionID,
        })
      );
    } else if (envIDs.length > 1) {
      $.post(
        this.correctPathname() + 'compare/' + envIDs.join('+'),
        JSON.stringify({
          sid: this.state.sessionID,
        })
      );
    }
  };

  onEnvDelete = (env2delete, previousEnv) => {
    this.sendSocketMessage({
      cmd: 'delete_env',
      prev_eid: previousEnv,
      eid: env2delete,
    });
  };

  onEnvSave = (env) => {
    if (!this.state.connected) {
      return;
    }

    this.updateLayout(this.state.layout);

    let payload = {};
    Object.keys(this.state.panes).map((paneID) => {
      payload[paneID] = JSON.parse(localStorage.getItem(this.keyLS(paneID)));
    });

    this.sendSocketMessage({
      cmd: 'save',
      data: payload,
      prev_eid: this.state.envID,
      eid: env,
    });

    let newEnvList = this.state.envList;
    if (newEnvList.indexOf(env) === -1) {
      newEnvList.push(env);
    }
    let layoutLists = this.state.layoutLists;

    for (var envIdx in newEnvList) {
      if (!layoutLists.has(newEnvList[envIdx])) {
        layoutLists.set(
          newEnvList[envIdx],
          new Map([[DEFAULT_LAYOUT, new Map()]])
        );
      }
    }

    this.setState({
      envList: newEnvList,
      layoutLists: layoutLists,
      envID: env,
      envIDs: [env],
    });
  };

  focusPane = (paneID, cb) => {
    this.setState(
      {
        focusedPaneID: paneID,
      },
      cb
    );
  };

  blurPane = (e) => {
    this.setState({
      focusedPaneID: null,
    });
  };

  resizePane = (layout, oldLayoutItem, layoutItem) => {
    // register a double click on the resize handle to reset the window size
    if (
      this.resize_click_happened &&
      layoutItem.w == oldLayoutItem.w &&
      layoutItem.h == oldLayoutItem.h
    ) {
      let pane = this.state.consistent_pane_copy[layoutItem.i];

      // resets to default layout (same as during pane creation)
      layoutItem.w = pane.width
        ? this.p2w(pane.width)
        : PANE_SIZE[pane.type][0];
      layoutItem.h = pane.height
        ? this.p2w(pane.height + 14)
        : PANE_SIZE[pane.type][1];
    }

    // update layout according to user interaction
    this.setState({
      layoutID: DEFAULT_LAYOUT,
    });
    this.focusPane(layoutItem.i);
    this.updateLayout(layout);
    this.sendLayoutItemState(layoutItem);

    // register a double click in this function
    this.resize_click_happened = true;
    setTimeout(
      function () {
        this.resize_click_happened = false;
      }.bind(this),
      400
    );
  };

  movePane = (layout, oldLayoutItem, layoutItem) => {
    this.setState({
      layoutID: DEFAULT_LAYOUT,
    });
    this.updateLayout(layout);
  };

  rebin = (layout) => {
    layout = layout ? layout : this.state.layout;
    let layoutID = this.state.layoutID;
    if (layoutID !== DEFAULT_LAYOUT) {
      let envLayoutList = this.getCurrLayoutList();
      let layoutMap = envLayoutList.get(this.state.layoutID);
      layout = layout.map((paneLayout, idx) => {
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
    let contents = layout.map((paneLayout, idx) => {
      return {
        width: paneLayout.w,
        height: paneLayout.h,
      };
    });

    this._bin = new Bin.ShelfFirst(contents, this.state.cols);
    return layout;
  };

  getCurrLayoutList() {
    if (this.state.layoutLists.has(this.state.envID)) {
      return this.state.layoutLists.get(this.state.envID);
    } else {
      return new Map();
    }
  }

  relayout = (pack) => {
    let layout = this.rebin();

    let sorted = sortLayout(layout);
    let newPanes = Object.assign({}, this.state.panes);
    let filter = this.getValidFilter(this.state.filter);
    let old_sorted = sorted.slice();
    let layoutID = this.state.layoutID;
    let envLayoutList = this.getCurrLayoutList();
    let layoutMap = envLayoutList.get(this.state.layoutID);
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
      let pos = this._bin.position(idx, this.state.cols);

      if (!newPanes[paneLayout.i]) debugger;
      newPanes[paneLayout.i].i = idx;

      return Object.assign({}, paneLayout, pos);
    });

    this.setState({
      panes: newPanes,
    });
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.panes = newPanes;
    this.updateLayout(newLayout);
  };

  toggleOnlineState = () => {
    if (this.state.connected) {
      this.disconnect();
    } else {
      this.connect();
    }
  };

  updateLayout = (layout) => {
    this.setState({ layout: layout }, (newState) => {
      this.state.layout.map((playout, idx) => {
        localStorage.setItem(this.keyLS(playout.i), JSON.stringify(playout));
      });
    });
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.layout = layout;
  };

  /**
   * Send layout item state to backend to update backend state.
   *
   * @param layout Layout to be sent to backend.
   */
  sendLayoutItemState = ({ i, h, w, x, y, moved, static: staticBool }) => {
    this.sendSocketMessage({
      cmd: 'layout_item_update',
      eid: this.state.envID,
      win: i,
      data: { i, h, w, x, y, moved, static: staticBool },
    });
  };

  updateToLayout = (layoutID) => {
    this.setState({
      layoutID: layoutID,
    });
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.layoutID = layoutID;
    if (layoutID !== DEFAULT_LAYOUT) {
      this.relayout();
      this.relayout();
      this.relayout();
    }
  };

  parseLayoutsFromServer(layoutJSON) {
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
    let currList = this.getCurrLayoutList();
    let layoutID = this.state.layoutID;
    if (!currList.has(this.state.layoutID)) {
      // If the current view was deleted by someone else (eek)
      layoutID = DEFAULT_LAYOUT;
    }
    this.setState({
      layoutLists: layoutLists,
      layoutID: layoutID,
    });
  }

  publishEvent = (event) => {
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
  sendPaneMessage = (data) => {
    if (this.state.focusedPaneID === null || this.state.readonly) {
      return;
    }
    let finalData = {
      target: this.state.focusedPaneID,
      eid: this.state.envID,
    };
    $.extend(finalData, data);
    this.sendSocketMessage({
      cmd: 'forward_to_vis',
      data: finalData,
    });
  };

  sendEmbeddingPop = (data) => {
    if (this.state.focusedPaneID === null || this.state.readonly) {
      return;
    }
    let finalData = {
      target: this.state.focusedPaneID,
      eid: this.state.envID,
    };
    $.extend(finalData, data);
    this.sendSocketMessage({
      cmd: 'pop_embeddings_pane',
      data: finalData,
    });
  };

  exportLayoutsToServer(layoutLists) {
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
    this.sendSocketMessage({
      cmd: 'save_layouts',
      data: exportForm,
    });
  }

  onLayoutSave(layoutName) {
    // Saves the current view as a new layout, pushes to the server
    let sorted = sortLayout(this.state.layout);
    let layoutMap = new Map();
    for (var idx = 0; idx < sorted.length; idx++) {
      let pane = this.state.panes[sorted[idx].i];
      let currLayout = getLayoutItem(this.state.layout, pane.id);
      layoutMap.set(sorted[idx].i, [idx, currLayout.h, currLayout.w]);
    }
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).set(layoutName, layoutMap);
    this.exportLayoutsToServer(layoutLists);
    this.setState({
      layoutLists: layoutLists,
      layoutID: layoutName,
    });
  }

  onLayoutDelete(layoutName) {
    // Deletes the selected view, pushes to server
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).delete(layoutName);
    this.exportLayoutsToServer(layoutLists);
    this.setState({
      layoutLists: layoutLists,
      layoutID: layoutLists.get(this.state.envID).keys()[0],
    });
  }

  updateDimensions() {
    this.setState({
      width: window.innerWidth,
      envSelectorStyle: {
        width: this.getEnvSelectWidth(window.innerWidth),
      },
    });
  }

  getEnvSelectWidth(w) {
    return Math.max(w / 3, 50);
  }

  UNSAFE_componentWillMount() {
    this.updateDimensions();
  }
  componentWillUnmount() {
    //Remove event listener
    window.removeEventListener('resize', this.updateDimensions);
  }

  componentDidMount() {
    window.addEventListener('resize', this.updateDimensions);
    this.setState({
      width: window.innerWidth,
      envSelectorStyle: {
        width: this.getEnvSelectWidth(window.innerWidth),
      },
    });
    this.connect();
  }

  componentDidUpdate() {
    if (this._firstLoad && this.state.sessionID) {
      this._firstLoad = false;
      if (this.state.envIDs.length > 0) {
        this.postForEnv(this.state.envIDs);
      } else {
        this.setState({
          envIDs: ['main'],
          envID: 'main',
        });
        this.postForEnv(['main']);
      }
    }

    // Bootstrap tooltips need some encouragement
    if (this.state.confirmClear) {
      $('#clear-button')
        .attr('data-original-title', 'Are you sure?')
        .tooltip('show');
    } else {
      $('#clear-button').attr(
        'data-original-title',
        'Clear Current Environment'
      );
    }
  }

  onWidthChange = (width, cols) => {
    this.setState(
      {
        cols: cols,
        width: width,
      },
      () => {
        this.relayout();
      }
    );
  };

  generateWindowHash = (windowId) => {
    let windowContent = this.state.panes[windowId];

    /*Convert JSON data to string with a space of 2. This detail is important.
    It ensures that the server and browser generate same JSON string */
    let content_string = JSON.stringify(windowContent, null, 2);
    return md5(content_string);
  };

  getWindowHash = (windowId) => {
    let url = 'http://' + window.location.host + '/win_hash';

    let body = {
      win: windowId,
      env: this.state.envID,
    };

    return $.post(url, JSON.stringify(body));
  };

  render() {
    let panes = Object.keys(this.state.panes).map((id) => {
      let pane = this.state.panes[id];

      try {
        let Comp = PANES[pane.type];
        if (!Comp) {
          throw new Error('unrecognized pane type: ' + pane);
        }
        let panelayout = getLayoutItem(this.state.layout, id);
        let filter = this.getValidFilter(this.state.filter);
        let isVisible = pane.title.match(filter);

        const PANE_TITLE_BAR_HEIGHT = 14;

        var _height = Math.round(this.h2p(panelayout.h));
        var _width = Math.round(this.w2p(panelayout.w));

        return (
          <div key={pane.id} className={isVisible ? '' : 'hidden-window'}>
            <ReactResizeDetector handleWidth handleHeight>
              <Comp
                {...pane}
                key={pane.id}
                onClose={this.closePane}
                onFocus={this.focusPane}
                onInflate={this.onInflate}
                isFocused={pane.id === this.state.focusedPaneID}
                w={panelayout.w}
                h={panelayout.h}
                width={this.w2p(panelayout.w)}
                height={this.h2p(panelayout.h) - PANE_TITLE_BAR_HEIGHT}
                _width={_width}
                _height={_height - PANE_TITLE_BAR_HEIGHT}
                appApi={{
                  sendPaneMessage: this.sendPaneMessage,
                  sendEmbeddingPop: this.sendEmbeddingPop,
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
              onClose={this.closePane}
              onFocus={this.focusPane}
              onInflate={this.onInflate}
              isFocused={pane.id === this.state.focusedPaneID}
              w={300}
              h={300}
              appApi={{ sendPaneMessage: this.sendPaneMessage }}
            />
          </div>
        );
      }
    });

    let modals = [
      <EnvModal
        key="EnvModal"
        activeEnv={this.state.envID}
        connected={this.state.connected}
        envList={this.state.envList}
        onEnvDelete={this.onEnvDelete}
        onEnvSave={this.onEnvSave}
        onModalClose={() => this.setState({ showEnvModal: false })}
        show={this.state.showEnvModal}
      />,
      <ViewModal
        key="ViewModal"
        activeLayout={this.state.layoutID}
        connected={this.state.connected}
        layoutList={this.getCurrLayoutList()}
        onModalClose={() => this.setState({ showViewModal: false })}
        onLayoutDelete={this.onLayoutDelete.bind(this)}
        onLayoutSave={this.onLayoutSave.bind(this)}
        show={this.state.showViewModal}
      />,
    ];

    let envControls = (
      <EnvControls
        connected={this.state.connected}
        envID={this.state.envID}
        envIDs={this.state.envIDs}
        envList={this.state.envList}
        envSelectorStyle={this.state.envSelectorStyle}
        onEnvClear={this.closeAllPanes}
        onEnvManageButton={() => {
          this.setState({ showEnvModal: !this.state.showEnvModal });
        }}
        onEnvSelect={this.onEnvSelect}
        readonly={this.state.readonly}
      />
    );
    let viewControls = (
      <ViewControls
        activeLayout={this.state.layoutID}
        connected={this.state.connected}
        envID={this.state.envID}
        layoutList={this.getCurrLayoutList()}
        onRepackButton={() => {
          this.relayout();
          this.relayout();
        }}
        onViewChange={this.updateToLayout}
        onViewManageButton={() => {
          this.setState({ showViewModal: !this.state.showViewModal });
        }}
        readonly={this.state.readonly}
      />
    );
    let filterControl = (
      <FilterControls
        filter={this.state.filter}
        onFilterChange={(ev) => {
          this.setState({ filter: ev.target.value }, () => {
            Object.keys(this.state.panes).map((paneID) => {
              this.focusPane(paneID);
            });
          });
          localStorage.setItem('filter', ev.target.value);
          // TODO remove this once relayout is moved to a post-state
          // update kind of thing
          this.state.filter = ev.target.value;
          this.relayout();
          this.relayout();
        }}
        onFilterClear={() => {
          this.setState({ filter: '' }, () => {
            Object.keys(this.state.panes).map((paneID) => {
              this.focusPane(paneID);
            });
          });
          // TODO remove this once relayout is moved to a post-state
          // update kind of thing
          this.state.filter = '';
          localStorage.setItem('filter', '');
          this.relayout();
          this.relayout();
        }}
      />
    );
    let connectionIndicator = (
      <ConnectionIndicator
        connected={this.state.connected}
        onClick={this.toggleOnlineState}
        readonly={this.state.readonly}
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
          onBlur={this.blurPane}
          onClick={this.publishEvent}
          onKeyUp={this.publishEvent}
          onKeyDown={this.publishEvent}
          onKeyPress={this.publishEvent}
        >
          <GridLayout
            className="layout"
            rowHeight={ROW_HEIGHT}
            autoSize={false}
            margin={[MARGIN, MARGIN]}
            layout={this.state.layout}
            draggableHandle={'.bar'}
            onLayoutChange={this.handleLayoutChange}
            onWidthChange={this.onWidthChange}
            onResizeStop={this.resizePane}
            onDragStop={this.movePane}
          >
            {panes}
          </GridLayout>
        </div>
      </div>
    );
  }
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
