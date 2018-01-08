/**
* Copyright 2017-present, Facebook, Inc.
* All rights reserved.
*
* This source code is licensed under the license found in the
* LICENSE file in the root directory of this source tree.
*
*/

'use strict';

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
};

const PANE_SIZE = {
  image: [20, 20],
  plot:  [30, 24],
  text:  [20, 20],
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

// TODO: Move some of this to smaller components and/or use something like redux
// to move state out of the app to a standalone store.
class App extends React.Component {
  state = {
    connected: false,
    sessionID: null,
    panes: {},
    focusedPaneID: null,
    envID: ACTIVE_ENV,
    saveText: ACTIVE_ENV,
    layoutID: DEFAULT_LAYOUT,
    // Bad form... make a copy of the global var we generated in python.
    envList: ENV_LIST.slice(),
    filter: '',
    filterField: '',
    layout: [],
    cols: 100,
    width: 1280,
    layoutLists: new Map([['main', new Map([[DEFAULT_LAYOUT, new Map()]])]]),
    showEnvModal: false,
    showViewModal: false,
    modifyID: null,
  };

  _bin = null;
  _socket = null;
  _envFieldRef = null;
  _filterFieldRef = null;
  _timeoutID = null;
  _pendingPanes = [];

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

  correctPathname = () => {
    var pathname = window.location.pathname;
    if (pathname.slice(-1) != '/') {
      pathname = pathname + '/'
    }
    return pathname
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
    let exists = newPane.id in newPanes
    newPanes[newPane.id] = newPane;

    if (!exists) {
      let stored = JSON.parse(localStorage.getItem(this.keyLS(newPane.id)));

      if (stored) {
        var paneLayout = stored;
        this._bin.content.push(paneLayout);
      } else {
        let w = PANE_SIZE[newPane.type][0], h = PANE_SIZE[newPane.type][1];

        if (newPane.width) w = this.p2w(newPane.width);
        if (newPane.height) h = Math.ceil(this.p2h(newPane.height + 14));
        if (newPane.content.caption) h += 1;

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
      if (newPane.content.caption) currLayout.h += 1;
    }
  }

  connect = () => {
    if (this._socket) {
      return;
    }

    var url = window.location;
    var socket = new WebSocket('ws://' + url.host + this.correctPathname() + 'socket');

    socket.onmessage = this._handleMessage;

    socket.onopen = () => {
      this.setState({connected: true});
    }

    socket.onerror = socket.onclose = () => {
      this.setState({connected: false}, () => {
        this._socket = null;
      });
    }

    this._socket = socket;
  }

  _handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);

    switch (cmd.command) {
      case 'register':
        this.setState({
          sessionID: cmd.data,
        }, () => {this.selectEnv(this.state.envID)});
        break;
      case 'pane':
      case 'window':
        this.addPaneBatched(cmd);
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
        this.setState({envList: cmd.data, layoutLists: layoutLists})
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
    Object.keys(this.state.panes).map((paneID) => {
      this.closePane(paneID, false, false);
    });
    this.rebin();
    this.setState({
      layout: [],
      panes: {},
      focusedPaneID: null,
    });
  }

  selectEnv = (envID) => {
    let isSameEnv = envID === this.state.envID;
    this.setState({
      envID: envID,
      saveText: envID,
      panes: isSameEnv ? this.state.panes : {},
      layout: isSameEnv ? this.state.layout : [],
      focusedPaneID: isSameEnv ? this.state.focusedPaneID : null,
    });
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    $.post(this.correctPathname() + 'env/' + envID,
      JSON.stringify({'sid' : this.state.sessionID}));
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
    });
  }

  focusPane = (paneID) => {
    this.setState({
      focusedPaneID: paneID,
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
    let filter = this.state.filter;
    let old_sorted = sorted.slice()
    let layoutID = this.state.layoutID
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

  saveLayout() {
    let sorted = sortLayout(this.state.layout);
    let layoutMap = new Map();
    for (var idx = 0; idx < sorted.length; idx++) {
      let pane = this.state.panes[sorted[idx].i];
      let currLayout = getLayoutItem(this.state.layout, pane.id);
      layoutMap.set(sorted[idx].i, [idx, currLayout.h, currLayout.w]);
    }
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).set(this.state.saveText, layoutMap);
    this.setState({layoutLists: layoutLists, layoutID: this.state.saveText});
  }

  deleteLayout() {
    let layoutLists = this.state.layoutLists;
    layoutLists.get(this.state.envID).delete(this.state.modifyID);
    this.setState({layoutLists: layoutLists});
  }

  componentDidMount() {
    this.connect();
  }

  onWidthChange = (width, cols) => {
    this.setState({cols: cols, width: width}, () => {this.relayout()});
  }

  openEnvModal() {
    this.setState({showEnvModal: true, saveText: this.state.envID});
  }

  closeEnvModal() {
    this.setState({showEnvModal: false});
  }

  openViewModal() {
    this.setState({showViewModal: true, saveText: this.state.layoutID});
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
            disabled={!this.state.connected}
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
            value={this.state.modifyID}>{
              this.state.envList.map((env) => {
                return <option key={env} value={env}>{env}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyID
                       || this.state.modifyID == 'main'}
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
        <strong>
          Currently these are only saved locally, and are lost on refresh
        </strong>
        <br/>
        <em>
          This feature is in beta, it's usually necessary to
          <br/>
          repack after selecting to restore your view
        </em>
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
            value={this.state.modifyID}>{
              Array.from(this.getCurrLayoutList().keys()).map((view) => {
                return <option key={view} value={view}>{view}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyID
                       || this.state.modifyID == DEFAULT_LAYOUT}
            onClick={this.deleteLayout.bind(this)}>
            Delete
          </button>
        </div>
      </ReactModal>
    );
  }

  renderEnvControls() {
    let env_options = this.state.envList.map((env) => {
      let check_space = ''
      if (env == this.state.envID) {
        check_space = <span>&nbsp;&#10003;</span>;
      }
      return <li>
        <a href="#" onClick={this.selectEnv.bind(this, env)}>
          {env}
          {check_space}
        </a>
      </li>;
    })
    return (
      <span>
        <span>Environment&nbsp;</span>
        <div className="btn-group navbar-btn" role="group" aria-label="Environment:">
          <div className="btn-group" role="group">
            <button className="btn btn-default dropdown-toggle"
                    type="button" id="envDropdown" data-toggle="dropdown"
                    aria-haspopup="true" aria-expanded="true">
              {this.state.envID}
              &nbsp;
              <span className="caret"></span>
            </button>
            <ul className="dropdown-menu" aria-labelledby="envDropdown">
              {env_options}
            </ul>
          </div>
          <button
            data-toggle="tooltip"
            title="Clear Current Environment"
            data-placement="bottom"
            className="btn btn-default"
            disabled={!this.state.connected}
            onClick={this.closeAllPanes}>
            <span
              className="glyphicon glyphicon-erase">
            </span>
          </button>
          <button
            data-toggle="tooltip"
            title="Manage Environments"
            data-placement="bottom"
            className="btn btn-default"
            disabled={!this.state.connected}
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
                    aria-haspopup="true" aria-expanded="true">
              {this.state.layoutID}
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
            disabled={!this.state.connected}
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
          onChange={(ev) => {this.setState(
            {filterField: ev.target.value}
          )}}
          value={this.state.filterField}
          ref={(ref) => this._filterFieldRef = ref}/>
        <span className="input-group-btn">
          <button
            type="button"
            className="btn btn-default"
            disabled={!this.state.connected}
            onClick={(ev) => {this.setState(
              {filter: this.state.filterField}, () => {
                Object.keys(this.state.panes).map((paneID) => {
                  this.focusPane(paneID);
                });
                // TODO remove this once relayout is moved to a post-state
                // update kind of thing
                this.state.filter = this.state.filterField
                this.relayout();
                this.relayout();
              }
            )}}>
            filter
          </button>
        </span>
      </div>
    )
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

      return (
        <div key={pane.id}
          style={pane.title.match(this.state.filter) ? {} : {display:'none'}}>
          <Comp
            {...pane}
            key={pane.id}
            onClose={this.closePane}
            onFocus={this.focusPane}
            onInflate={this.onInflate}
            isFocused={pane.id === this.state.focusedPaneID}
            w={panelayout.w}
            h={panelayout.h}
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
                'btn-success': this.state.connected,
                'btn-danger': !this.state.connected})}
              onClick={this.toggleOnlineState}>
              {this.state.connected ? 'online' : 'offline'}
            </button>
          </span>
        </div>
        <div>
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
