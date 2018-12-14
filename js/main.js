/**
* Copyright 2017-present, Facebook, Inc.
* All rights reserved.
*
* This source code is licensed under the license found in the
* LICENSE file in the root directory of this source tree.
*
*/

'use strict';
import React from 'react';
import ReactModal from 'react-modal';
var classNames = require('classnames');
import 'rc-tree-select/assets/index.css';

import TreeSelect, { SHOW_CHILD } from 'rc-tree-select';
import EventSystem from './EventSystem'

var ReactGridLayout = require('react-grid-layout');

import createClass from 'create-react-class';
import PropTypes from 'prop-types';

var md5 = require('md5');

const PropertiesPane = require('./PropertiesPane');
const TextPane = require('./TextPane');
const ImagePane = require('./ImagePane');
const PlotPane = require('./PlotPane');

const WidthProvider = require('./Width').default;

const GridLayout = WidthProvider(ReactGridLayout);
const sortLayout = ReactGridLayout.utils.sortLayoutItemsByRowCol;
const getLayoutItem = ReactGridLayout.utils.getLayoutItem;

const ROW_HEIGHT = 5; // pixels
const MARGIN = 10; // pixels

const PANES = {
  image: ImagePane,
  plot: PlotPane,
  text: TextPane,
  properties: PropertiesPane,
};

const PANE_SIZE = {
  image: [20, 20],
  plot:  [30, 24],
  text:  [20, 20],
  properties:  [20, 20],
};

const MODAL_STYLE = {
  content : {
    top                   : '50%',
    left                  : '50%',
    right                 : 'auto',
    bottom                : 'auto',
    marginRight           : '-50%',
    transform             : 'translate(-50%, -50%)'
  }
};

const DEFAULT_LAYOUT = 'current';

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
  use_env = localStorage.getItem( 'envID' ) || 'main';
  use_envs = JSON.parse(localStorage.getItem( 'envIDs' )) || ['main']
}

// TODO: Move some of this to smaller components and/or use something like redux
// to move state out of the app to a standalone store.
class App extends React.Component {
  state = {
    connected: false,
    readonly: false,
    sessionID: null,
    panes: {},
    focusedPaneID: null,
    envID: use_env,
    envIDs: use_envs,
    saveText: ACTIVE_ENV,
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
    modifyID: null,
    treeDataSimpleMode: {
      id: 'key',
      rootPId: 0
    },
    envSelectorStyle: {width: 1280/2 },
    flexSelectorOnHover: false,
    confirmClear: false,
  };

  _bin = null;
  _socket = null;
  _envFieldRef = null;
  _timeoutID = null;
  _pendingPanes = [];
  _firstLoad = true;

  constructor() {
    super();
    this.updateDimensions = this.updateDimensions.bind(this);
  }

  colWidth = () => {
    return (this.state.width - (MARGIN * (this.state.cols - 1))
      - (MARGIN * 2)) / this.state.cols;
  }

  p2w = (w) => {  // translate pixels -> RGL grid coordinates
    let colWidth = this.colWidth();
    return (w + MARGIN) / (colWidth + MARGIN);
  }

  p2h = (h) => {
    return (h + MARGIN) / (ROW_HEIGHT + MARGIN);
  }

  keyLS = (key) => {      // append env to pane id for localStorage key
    return this.state.envID + '_' + key;
  }

  getValidFilter = (filter) => {
    // Ensure the regex filter is valid
    try {
      'test_string'.match(filter);
    } catch(e) {
      filter = '';
    }
    return filter
  }

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
  }

  addPaneBatched = (pane) => {
    if (!this._timeoutID) {
      this._timeoutID = setTimeout(this.processBatchedPanes, 100);
    }
    this._pendingPanes.push(pane);
  }

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
  }

  processPane = (newPane, newPanes, newLayout) => {
    let exists = newPane.id in newPanes;
    newPanes[newPane.id] = newPane;

    if (!exists) {
      let stored = JSON.parse(localStorage.getItem(this.keyLS(newPane.id)));
      if (this._bin == null) {
        this.rebin();
      }
      if (stored) {
        var paneLayout = stored;
        this._bin.content.push(paneLayout);
      } else {
        let w = PANE_SIZE[newPane.type][0], h = PANE_SIZE[newPane.type][1];

        if (newPane.width) w = this.p2w(newPane.width);
        if (newPane.height) h = Math.ceil(this.p2h(newPane.height + 14));
        if (newPane.content && newPane.content.caption) h += 1;

        this._bin.content.push({width: w, height: h});

        let pos = this._bin.position(newLayout.length, this.state.cols);

        var paneLayout = {
          i: newPane.id,
          w: w, h: h,
          width: w, height: h,
          x: pos.x, y: pos.y,
          static: false,
        }
      }

      newLayout.push(paneLayout);
    } else {
      let currLayout = getLayoutItem(newLayout, newPane.id);
      if (newPane.width) currLayout.w = this.p2w(newPane.width);
      if (newPane.height) currLayout.h = Math.ceil(this.p2h(newPane.height + 14));
      if (newPane.content && newPane.content.caption) currLayout.h += 1;
    }
  }

  connect = () => {
    if (this._socket) {
      return;
    }
    var url = window.location;
    var ws_protocol = null;
    if (url.protocol == "https:") {
      ws_protocol = 'wss';
    } else {
      ws_protocol = 'ws';
    }
    var socket = new WebSocket(ws_protocol + '://' + url.host + this.correctPathname() + 'socket');

    socket.onmessage = this._handleMessage;

    socket.onopen = () => {
      this.setState({connected: true});
    };

    socket.onerror = socket.onclose = () => {
      this.setState({connected: false}, function () {
        this._socket = null;
      });
    };

    this._socket = socket;
  }

  _handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);
    switch (cmd.command) {
      case 'register':
        this.setState({
          sessionID: cmd.data,
          readonly: cmd.readonly,
        }, () => {this.postForEnv(this.state.envIDs);});
        break;
      case 'pane':
      case 'window':
        // If we're in compare mode and recieve an update to an environment
        // that is selected that isn't from the compare output, we need to
        // reload the compare output
        if (this.state.envIDs.length > 1 && cmd.has_compare !== true) {
          this.postForEnv(this.state.envIDs);
        } else {
          this.addPaneBatched(cmd);
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
        let layoutLists = this.state.layoutLists;
        for (var envIdx in cmd.data) {
          if (!layoutLists.has(cmd.data[envIdx])) {
            layoutLists.set(cmd.data[envIdx],
                            new Map([[DEFAULT_LAYOUT, new Map()]]));
          }
        }
        if (!this.state.showEnvModal || (this.state.modifyID in cmd.data)) {
          this.setState({envList: cmd.data, layoutLists: layoutLists})
        } else {
          this.setState({
            envList: cmd.data,
            layoutLists: layoutLists,
            modifyID: cmd.data[0],
          })
        }
        break;
      case 'layout_update':
        this.parseLayoutsFromServer(cmd.data);
        break;
      default:
        console.error('unrecognized command', cmd);
    }
  }

  disconnect = () => {
    this._socket.close();
  }

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
    delete newPanes[paneID];
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
        (paneLayout) => paneLayout.i !== paneID)

      this.setState({
        layout: newLayout,
        panes: newPanes,
        focusedPaneID: focusedPaneID === paneID ? null : focusedPaneID,
      }, () => {this.relayout();});
    }
  }

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
      focusedPaneID: null,
      confirmClear: false,
    });
  }

  triggerClear = () => {
    if (this.state.confirmClear) {
      this.closeAllPanes();
    } else {
      this.setState({confirmClear: true});
    }
  }

  cancelClear = () => {
    if (this.state.confirmClear) {
      this.setState({confirmClear: false});
    }
  }

  selectEnv = (selectedNodes) => {
    var isSameEnv = selectedNodes.length == this.state.envIDs.length;
    if (isSameEnv) {
      for (var i=0; i<selectedNodes.length; i++) {
        if (selectedNodes[i] != this.state.envIDs[i]) {
          isSameEnv=false;
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
      saveText: envID,
      panes: isSameEnv ? this.state.panes : {},
      layout: isSameEnv ? this.state.layout : [],
      focusedPaneID: isSameEnv ? this.state.focusedPaneID : null,
    });
    localStorage.setItem('envID', envID);
    localStorage.setItem('envIDs', JSON.stringify(selectedNodes));
    this.postForEnv(selectedNodes);
  }

  postForEnv = (envIDs) => {
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    if (envIDs.length == 1 ) {
      $.post(this.correctPathname() + 'env/' + envIDs[0],
             JSON.stringify({'sid' : this.state.sessionID}));
    }
    else if(envIDs.length > 1) {
      $.post(this.correctPathname() + 'compare/' + envIDs.join('+'),
             JSON.stringify({'sid' : this.state.sessionID}));

    }
  }

  deleteEnv = () => {
    this.sendSocketMessage({
      cmd: 'delete_env',
      prev_eid: this.state.envID,
      eid: this.state.modifyID,
    });
  }

  saveEnv = () => {
    if (!this.state.connected) {
      return;
    }

    this.updateLayout(this.state.layout);

    let env = this._envFieldRef.value;

    let payload = {};
    Object.keys(this.state.panes).map((paneID) => {
      payload[paneID] = JSON.parse(localStorage.getItem(this.keyLS(paneID)));
    });

    this.sendSocketMessage({
      cmd: 'save',
      data: payload,
      prev_eid: this.state.envID,
      eid: env
    });

    let newEnvList = this.state.envList;
    if (newEnvList.indexOf(env) === -1) {
      newEnvList.push(env);
    }
    let layoutLists = this.state.layoutLists;

    for (var envIdx in newEnvList) {
      if (!layoutLists.has(newEnvList[envIdx])) {
        layoutLists.set(newEnvList[envIdx],
          new Map([[DEFAULT_LAYOUT, new Map()]]));
      }
    }

    this.setState({
      envList: newEnvList,
      layoutLists: layoutLists,
      envID: env,
      envIDs: [env],
    });
  }

  focusPane = (paneID, cb) => {
    this.setState({
      focusedPaneID: paneID,
    }, cb);
  }

  blurPane = (e) => {
    this.setState({
      focusedPaneID: null,
    });
  }

  resizePane = (layout, oldLayoutItem, layoutItem) => {
    this.setState({'layoutID': DEFAULT_LAYOUT})
    this.focusPane(layoutItem.i);
    this.updateLayout(layout);
  }

  movePane = (layout, oldLayoutItem, layoutItem) => {
    this.setState({'layoutID': DEFAULT_LAYOUT})
    this.updateLayout(layout);
  }

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
  }

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
    sorted = sorted.sort(function(a, b) {
      let diff = (newPanes[a.i].title.match(filter) != null) -
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
      return old_sorted.indexOf(a) - old_sorted.indexOf(b);  // stable sort
    });

    let newLayout = sorted.map((paneLayout, idx) => {
      let pos = this._bin.position(idx, this.state.cols);

      if (!newPanes[paneLayout.i]) debugger;
      newPanes[paneLayout.i].i = idx;

      return Object.assign({}, paneLayout, pos);
    });

    this.setState({panes: newPanes});
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.panes = newPanes;
    this.updateLayout(newLayout);
  }

  toggleOnlineState = () => {
    if (this.state.connected) {
      this.disconnect();
    } else {
      this.connect();
    }
  }

  updateLayout = (layout) => {
    this.setState({layout: layout}, (newState) => {
      this.state.layout.map((playout, idx) => {
        localStorage.setItem(this.keyLS(playout.i), JSON.stringify(playout));
      });
    });
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.layout = layout;
  }

  updateToLayout = (layoutID) => {
    this.setState({layoutID: layoutID});
    // TODO this is very non-conventional react, someday it shall be fixed but
    // for now it's important to fix relayout grossness
    this.state.layoutID = layoutID;
    if (layoutID !== DEFAULT_LAYOUT) {
      this.relayout();
      this.relayout();
      this.relayout();
    }
  }

  parseLayoutsFromServer(layoutJSON) {
    // Handles syncing layout state from the server
    if (layoutJSON.length == 0) {
      return;  // Skip totally blank updates, these are empty inits
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
    this.setState({layoutLists: layoutLists, layoutID: layoutID});
  }

  publishEvent = (event) => {
    EventSystem.publish('global.event', event);
  }

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
  }

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

  saveLayout() {
    // Saves the current view as a new layout, pushes to the server
    let sorted = sortLayout(this.state.layout);
    let layoutMap = new Map();
    for (var idx = 0; idx < sorted.length; idx++) {
      let pane = this.state.panes[sorted[idx].i];
      let currLayout = getLayoutItem(this.state.layout, pane.id);
      layoutMap.set(sorted[idx].i, [idx, currLayout.h, currLayout.w]);
    }
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).set(this.state.saveText, layoutMap);
    this.exportLayoutsToServer(layoutLists);
    this.setState({layoutLists: layoutLists, layoutID: this.state.saveText});
  }

  deleteLayout() {
    // Deletes the selected view, pushes to server
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).delete(this.state.modifyID);
    this.exportLayoutsToServer(layoutLists);
    this.setState({layoutLists: layoutLists});
  }

  updateDimensions() {
    this.setState({
      'width': window.innerWidth,
      'envSelectorStyle': {width: this.getEnvSelectWidth(window.innerWidth)}
    });
  }

  getEnvSelectWidth(w) {
    return Math.max(w/3,50);
  }

  componentWillMount() {
    this.updateDimensions();
  }
  componentWillUnmount() {
    //Remove event listener
    window.removeEventListener("resize", this.updateDimensions);
  }

  componentDidMount() {
    window.addEventListener("resize", this.updateDimensions);
    this.setState({
      'width':window.innerWidth,
      'envSelectorStyle': {width: this.getEnvSelectWidth(window.innerWidth)}
    });
    this.connect();
  }

  componentDidUpdate() {
    if (this._firstLoad && this.state.sessionID) {
      this._firstLoad = false;
      if (this.state.envIDs.length > 0) {
        this.postForEnv(this.state.envIDs);
      }
      else {
        this.setState({
          'envIDs': ['main'],
          'envID': 'main'
        });
        this.postForEnv(['main']);
      }
    }

    // Bootstrap tooltips need some encouragement
    if (this.state.confirmClear) {
      $("#clear-button").attr('data-original-title', "Are you sure?")
                        .tooltip('fixTitle')
                        .tooltip('show');
    } else {
      $("#clear-button").attr('data-original-title', "Clear Current Environment")
                        .tooltip('fixTitle');
    }
  }

  onWidthChange = (width, cols) => {
    this.setState({cols: cols, width: width}, () => {this.relayout()});
  }

  generateWindowHash = (windowId) => {
    let windowContent = this.state.panes[windowId];

    /*Convert JSON data to string with a space of 2. This detail is important.
    It ensures that the server and browser generate same JSON string */
    let content_string = JSON.stringify(windowContent, null, 2);
    return md5(content_string)
  }

  getWindowHash = (windowId) => {
    let url = "http://" + window.location.host + "/win_hash";

    let body = {
      "win" : windowId,
      "env" : this.state.envID
    }

    return $.post(url, JSON.stringify(body))
  }

  openEnvModal() {
    this.setState({
      showEnvModal: true,
      saveText: this.state.envID,
      modifyID: this.state.envList[0],
    });
  }

  closeEnvModal() {
    this.setState({showEnvModal: false});
  }

  openViewModal() {
    this.setState({
      showViewModal: true,
      saveText: this.state.layoutID,
      modifyID: this.state.layoutLists.get(this.state.envID).keys()[0],
    });
  }

  closeViewModal() {
    this.setState({showViewModal: false});
  }

  renderEnvModal() {
    return (
      <ReactModal
        isOpen={this.state.showEnvModal}
        onRequestClose={this.closeEnvModal.bind(this)}
        contentLabel="Environment Management Modal"
        ariaHideApp={false}
        style={MODAL_STYLE}
      >
        <span className="visdom-title">Manage Environments</span>
        <br/>
        Save or fork current environment:
        <br/>
        <div className="form-inline">
          <input
            className="form-control"
            type="text"
            onChange={(ev) => {this.setState({saveText: ev.target.value})}}
            value={this.state.saveText}
            ref={(ref) => this._envFieldRef = ref}
          />
          <button
            className="btn btn-default"
            disabled={!(this.state.connected && this.state.envID &&
                      (this.state.saveText.length > 0))}
            onClick={this.saveEnv}>
            {this.state.envList.indexOf(
              this.state.saveText) >= 0 ? 'save' : 'fork'}
          </button>
        </div>
        <br/>
        Delete environment selected in dropdown:
        <br/>
        <div className="form-inline">
          <select
            className="form-control"
            disabled={!this.state.connected}
            onChange={(ev) => {this.setState({modifyID: ev.target.value})}}
            value={this.state.modifyID}>
            {
              this.state.envList.map((env) => {
                return <option key={env} value={env}>{env}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyID ||
                      this.state.modifyID == 'main'}
            onClick={this.deleteEnv.bind(this)}>
            Delete
          </button>
        </div>
      </ReactModal>
    );
  }

  renderViewModal() {
    return (
      <ReactModal
        isOpen={this.state.showViewModal}
        onRequestClose={this.closeViewModal.bind(this)}
        contentLabel="Layout Views Management Modal"
        ariaHideApp={false}
        style={MODAL_STYLE}
      >
        <span className="visdom-title">Manage Views</span>
        <br/>
        Save or fork current layout:
        <br/>
        <div className="form-inline">
          <input
            className="form-control"
            type="text"
            onChange={(ev) => {this.setState({saveText: ev.target.value})}}
            value={this.state.saveText}
          />
          <button
            className="btn btn-default"
            disabled={!this.state.connected ||
                      this.state.saveText == DEFAULT_LAYOUT}
            onClick={this.saveLayout.bind(this)}>
            {this.getCurrLayoutList().has(
              this.state.saveText) ? 'save' : 'fork'}
          </button>
        </div>
        <br/>
        Delete layout view selected in dropdown:
        <br/>
        <div className="form-inline">
          <select
            className="form-control"
            disabled={!this.state.connected}
            onChange={(ev) => {this.setState({modifyID: ev.target.value})}}
            value={this.state.modifyID}>
            {
              Array.from(this.getCurrLayoutList().keys()).map((view) => {
                return <option key={view} value={view}>{view}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyID ||
                      this.state.modifyID == DEFAULT_LAYOUT}
            onClick={this.deleteLayout.bind(this)}>
            Delete
          </button>
        </div>
      </ReactModal>
    );
  }

  mouseOverSelect = () => {
    if (this.state.flexSelectorOnHover) {
      this.setState({
        'envSelectorStyle': {
          display: 'flex',
          width: this.getEnvSelectWidth(this.state.width),
          'min-width': this.getEnvSelectWidth(this.state.width),
          'flex-direction': 'column'
        }
      });
    }
  }

  mouseOutSelect = () => {
    if (this.state.flexSelectorOnHover) {
      this.setState({
        'envSelectorStyle': {
          display: 'block',
          width: this.getEnvSelectWidth(this.state.width),
          height: 30,
          overflow: 'auto'
        }
      });
    }
  }

  renderEnvControls() {
    var slist = this.state.envList.slice();
    slist.sort();
    var roots = Array.from(
      new Set(slist.map((x) => {return x.split('_')[0];}))
    );

    let env_options2 = slist.map((env, idx) => {
      //var check_space = this.state.envIDs.includes(env);
      if (env.split('_').length == 1) {
        return null;
      }
      return {
        key:idx + 1 + roots.length,
        pId:roots.indexOf(env.split('_')[0]) + 1,
        label: env,
        value: env
      };
    });

    env_options2 = env_options2.filter(x => x != null);

    env_options2 = env_options2.concat(roots.map((x, idx) => { return {
      key: idx+1,
      pId: 0,
      label: x,
      value: x
    };}));

    if (this.state.confirmClear) {
      var clearText = "Are you sure?";
      var clearStyle = "btn btn-warning";
    } else {
      var clearText = "Clear Current Environment";
      var clearStyle = "btn btn-default";
    }

    return (
      <span>
        <span>Environment&nbsp;</span>
        <div className="btn-group navbar-btn"
          role="group"
          aria-label="Environment:">
          <div className="btn-group"
            role="group"
            onMouseEnter={this.mouseOverSelect}
            onMouseLeave={this.mouseOutSelect}>
            <TreeSelect
              style={this.state.envSelectorStyle}
              allowClear={true}
              dropdownStyle={{maxHeight: 900, overflow: 'auto'}}
              placeholder={<i>Select environment(s)</i>}
              searchPlaceholder="search"
              treeLine maxTagTextLength={1000}
              inputValue={null}
              value={this.state.envIDs}
              treeData={env_options2}
              treeDefaultExpandAll
              treeNodeFilterProp="title"
              treeDataSimpleMode={this.state.treeDataSimpleMode}
              treeCheckable showCheckedStrategy={SHOW_CHILD}
              dropdownMatchSelectWidth={false}
              onChange={this.selectEnv}
            />
          </div>
          <button
            id="clear-button"
            data-toggle="tooltip"
            title={clearText}
            data-placement="bottom"
            className={clearStyle}
            disabled={!(this.state.connected && this.state.envID && !this.state.readonly)}
            onClick={this.triggerClear}
            onBlur={this.cancelClear}>
            <span
              className="glyphicon glyphicon-erase">
            </span>
          </button>
          <button
            data-toggle="tooltip"
            title="Manage Environments"
            data-placement="bottom"
            className="btn btn-default"
            disabled={!(this.state.connected && this.state.envID && !this.state.readonly)}
            onClick={this.openEnvModal.bind(this)}>
            <span
              className="glyphicon glyphicon-folder-open">
            </span>
          </button>
        </div>
      </span>
    )
  }

  renderViewControls() {
    let view_options = Array.from(
      this.getCurrLayoutList().keys()).map((view) => {
        let check_space = ''
        if (view == this.state.layoutID) {
          check_space = <span>&nbsp;&#10003;</span>;
        }
        return <li>
          <a href="#" onClick={this.updateToLayout.bind(this, view)}>
            {view}
            {check_space}
          </a>
        </li>;
      }
    )
    return (
      <span>
        <span>View&nbsp;</span>
        <div className="btn-group navbar-btn" role="group" aria-label="View:">
          <div className="btn-group" role="group">
            <button className="btn btn-default dropdown-toggle"
              type="button" id="viewDropdown" data-toggle="dropdown"
              aria-haspopup="true" aria-expanded="true"
              disabled={!(this.state.connected && this.state.envID)}>
              {(this.state.envID == null) ? 'compare' : this.state.layoutID}
              &nbsp;
              <span className="caret"></span>
            </button>
            <ul className="dropdown-menu" aria-labelledby="viewDropdown">
              {view_options}
            </ul>
          </div>
          <button
            data-toggle="tooltip"
            title="Repack"
            data-placement="bottom"
            className="btn btn-default"
            onClick={(ev) => {this.relayout(); this.relayout();}}>
            <span
              className="glyphicon glyphicon-th">
            </span>
          </button>
          <button
            data-toggle="tooltip"
            title="Manage Views"
            data-placement="bottom"
            className="btn btn-default"
            disabled={!(this.state.connected && this.state.envID && !this.state.readonly)}
            onClick={(ev) => {this.openViewModal()}}>
            <span
              className="glyphicon glyphicon-folder-open">
            </span>
          </button>
        </div>
      </span>
    )
  }

  renderFilterControl() {
    return (
      <div className="input-group navbar-btn">
        <input type="text" className="form-control" placeholder="Filter text"
          onChange={(ev) => {
            this.setState(
              {filter: ev.target.value}, () => {
                Object.keys(this.state.panes).map((paneID) => {
                  this.focusPane(paneID);
                });
              }
            );
            localStorage.setItem('filter', ev.target.value);
            // TODO remove this once relayout is moved to a post-state
            // update kind of thing
            this.state.filter = ev.target.value;
            this.relayout();
            this.relayout();
          }}
          value={this.state.filter}/>
        <span className="input-group-btn">
          <button
            data-toggle="tooltip"
            title="Clear filter"
            data-placement="bottom"
            type="button"
            className="btn btn-default"
            onClick={(ev) => {this.setState(
              {filter: ''}, () => {
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
            }}>
            <span
              className="glyphicon glyphicon-erase">
            </span>
          </button>
        </span>
      </div>
    );
  }

  render() {
    let panes = Object.keys(this.state.panes).map((id) => {
      let pane = this.state.panes[id];
      let Comp = PANES[pane.type];
      if (!Comp) {
        console.error('unrecognized pane type: ', pane);
        return null;
      }
      let panelayout = getLayoutItem(this.state.layout, id);
      let filter = this.getValidFilter(this.state.filter);
      let isVisible = pane.title.match(filter)
      return (
        <div key={pane.id}
          className={isVisible? '' : 'hidden-window'}>
          <Comp
            {...pane}
            key={pane.id}
            onClose={this.closePane}
            onFocus={this.focusPane}
            onInflate={this.onInflate}
            isFocused={pane.id === this.state.focusedPaneID}
            w={panelayout.w}
            h={panelayout.h}
            appApi={{sendPaneMessage: this.sendPaneMessage}}
          />
        </div>
      );
    });

    let envModal = this.renderEnvModal();
    let viewModal = this.renderViewModal();
    let envControls = this.renderEnvControls();
    let viewControls = this.renderViewControls();
    let filterControl = this.renderFilterControl();

    return (
      <div>
        {envModal}
        {viewModal}
        <div className="navbar-form navbar-default">
          <span className="navbar-brand visdom-title">visdom</span>
          <span className="vertical-line"></span>
          &nbsp;&nbsp;
          {envControls}
          &nbsp;&nbsp;
          <span className="vertical-line"></span>
          &nbsp;&nbsp;
          {viewControls}
          <span style={{float: 'right'}}>
            {filterControl}
            &nbsp;&nbsp;
            <button
              className={classNames({
                'btn': true,
                'btn-warning': this.state.connected && this.state.readonly,
                'btn-success': this.state.connected && !this.state.readonly,
                'btn-danger': !this.state.connected
                })}
              onClick={this.toggleOnlineState}>
              {this.state.connected ? (this.state.readonly ? 'readonly' : 'online') : 'offline'}
            </button>
          </span>
        </div>
        <div
          tabIndex="-1"
          className="no-focus"
          onBlur={this.blurPane}
          onKeyUp={this.publishEvent}
          onKeyDown={this.publishEvent}
          onKeyPress={this.publishEvent}
        >
          <GridLayout
            className="layout"
            rowHeight={ROW_HEIGHT}
            autoSize={false}
            margin={[MARGIN,MARGIN]}
            layout={this.state.layout}
            draggableHandle={'.bar'}
            onLayoutChange={this.handleLayoutChange}
            onWidthChange={this.onWidthChange}
            onResizeStop={this.resizePane}
            onDragStop={this.movePane}>
            {panes}
          </GridLayout>
        </div>
      </div>
    )
  }
}


function load() {
  ReactDOM.render(
    <App />,
    document.getElementById('app')
  );
  document.removeEventListener('DOMContentLoaded', load);
}

document.addEventListener('DOMContentLoaded', load);

$(document).ready(function(){
  $('[data-toggle="tooltip"]').tooltip({
    container: 'body',
    delay: {show: 600, hide: 100},
    trigger : 'hover',
  });
});
