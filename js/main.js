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

const DEFAULT_LAYOUT = 'default';

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
    layoutLists: {[DEFAULT_LAYOUT]: []},
    showEnvModal: false,
    showViewModal: false,
    modifyEnv: null,
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
        this.setState({envList: cmd.data})
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
      eid: this.state.modifyEnv,
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
    this.setState({
      envList: newEnvList,
      envID: env,
    });
  }

  focusPane = (paneID) => {
    this.setState({
      focusedPaneID: paneID,
    });
  }

  resizePane = (layout, oldLayoutItem, layoutItem) => {
    this.focusPane(layoutItem.i);
    this.updateLayout(layout);
  }

  movePane = (layout, oldLayoutItem, layoutItem) => {
    this.updateLayout(layout);
  }

  rebin = (layout) => {
    layout = layout ? layout : this.state.layout;
    let contents = layout.map((paneLayout, idx) => {
      return {
        width: paneLayout.w,
        height: paneLayout.h,
      };
    });

    this._bin = new Bin.ShelfFirst(contents, this.state.cols);
  }

  relayout = (pack) => {
    this.rebin();

    let sorted = sortLayout(this.state.layout);
    let newPanes = Object.assign({}, this.state.panes);
    let filter = this.state.filter;
    let old_sorted = sorted.slice()
    // Sort out things that were filtered away
    sorted = sorted.sort(function(a, b) {
      let diff = (newPanes[a.i].title.match(filter) != null) -
              (newPanes[b.i].title.match(filter) != null);
      if (diff != 0) {
        return -diff;
      }
      else return old_sorted.indexOf(a) - old_sorted.indexOf(b);  // stable sort
    });

    let newLayout = sorted.map((paneLayout, idx) => {
      let pos = this._bin.position(idx, this.state.cols);

      if (!newPanes[paneLayout.i]) debugger;
      newPanes[paneLayout.i].i = idx;

      return Object.assign({}, paneLayout, pos);
    });

    this.setState({panes: newPanes});
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
    this.setState(
      {layoutID: DEFAULT_LAYOUT, layout: layout},
      (newState) => {
        this.state.layout.map((playout, idx) => {
          localStorage.setItem(this.keyLS(playout.i), JSON.stringify(playout));
        });
      }
    );
  }

  updateToLayout = (layoutID) => {
    this.setState({layoutID: layoutID});
    if (layoutID !== '') {
      this.updateLayout(this.state.layoutList[layoutID]);
    }
  }

  componentDidMount() {
    this.connect();
  }

  onWidthChange = (width, cols) => {
    this.setState({cols: cols, width: width}, () => {this.relayout()});
  }

  openEnvModal() {
    this.setState({showEnvModal: true});
  }

  afterOpenEnvModal() {
    // do something here?
  }

  closeEnvModal() {
    this.setState({showEnvModal: false});
  }

  openViewModal() {
    this.setState({showViewModal: true});
  }

  afterOpenViewModal() {
    // do something here?
  }

  closeViewModal() {
    this.setState({showViewModal: false});
  }

  renderEnvModal() {
    return (
      <ReactModal
        isOpen={this.state.showEnvModal}
        onAfterOpen={this.afterOpenEnvModal.bind(this)}
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
        Clear contents of current environment:
        <br/>
        <div className="form-inline">
          <button
            className="btn btn-default"
            disabled={!this.state.connected}
            onClick={this.closeAllPanes}>
            clear
          </button>
        </div>
        <br/>
        Delete environment selected in dropdown:
        <br/>
        <div className="form-inline">
          <select
            className="form-control"
            disabled={!this.state.connected}
            onChange={(ev) => {this.setState({modifyEnv: ev.target.value})}}
            value={this.state.modifyEnv}>{
              this.state.envList.map((env) => {
                return <option key={env} value={env}>{env}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyEnv
                       || this.state.modifyEnv == 'main'}
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
        isOpen={this.state.showEnvModal}
        onAfterOpen={this.afterOpenEnvModal.bind(this)}
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
        Clear contents of current environment:
        <br/>
        <div className="form-inline">
          <button
            className="btn btn-default"
            disabled={!this.state.connected}
            onClick={this.closeAllPanes}>
            clear
          </button>
        </div>
        <br/>
        Delete environment selected in dropdown:
        <br/>
        <div className="form-inline">
          <select
            className="form-control"
            disabled={!this.state.connected}
            onChange={(ev) => {this.setState({modifyEnv: ev.target.value})}}
            value={this.state.modifyEnv}>{
              this.state.envList.map((env) => {
                return <option key={env} value={env}>{env}</option>;
              })
            }
          </select>
          <button
            className="btn btn-default"
            disabled={!this.state.connected || !this.state.modifyEnv
                       || this.state.modifyEnv == 'main'}
            onClick={this.deleteEnv.bind(this)}>
            Delete
          </button>
        </div>
      </ReactModal>
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

    return (
      <div>
        {envModal}
        <div className="navbar navbar-default">
          <div className="form-inline">
            <span className="visdom-title">visdom</span>
            <button
              className="btn btn-default"
              onClick={this.relayout}>
              <span
                className="glyphicon glyphicon-th">
              </span>
            </button>
            <select
              className="form-control"
              disabled={!this.state.connected}
              onChange={(ev) => {this.selectEnv(ev.target.value)}}
              value={this.state.envID}>{
                this.state.envList.map((env) => {
                  return <option key={env} value={env}>{env}</option>;
                })
              }
            </select>
            <button
              className="btn btn-default"
              disabled={!this.state.connected}
              onClick={this.openEnvModal.bind(this)}>
              manage envs
            </button>
            <select
              className="form-control"
              disabled={!this.state.connected}
              onChange={(ev) => {this.updateToLayout(ev.target.value)}}
              value={this.state.layoutID}>{
                this.state.layoutList.map((env) => {
                  return <option key={env} value={env}>{env}</option>;
                })
              }
            </select>
            <button
              className="btn btn-default"
              disabled={!this.state.connected}
              onClick={(ev) => {this.renderLayoutDialog()}}>
              manage layouts
            </button>
            <input
              className="form-control"
              type="text"
              onChange={(ev) => {this.setState(
                {filterField: ev.target.value}
              )}}
              value={this.state.filterField}
              ref={(ref) => this._filterFieldRef = ref}
            />
            <button
              className="btn btn-default"
              disabled={!this.state.connected}
              onClick={(ev) => {this.setState(
                {filter: this.state.filterField}, () => {
                  Object.keys(this.state.panes).map((paneID) => {
                    this.focusPane(paneID);
                  });
                  this.relayout();
                }
              )}}>
              filter
            </button>
            <button
              style={{float: 'right'}}
              className={classNames({
                'btn': true, 'btn-success': this.state.connected,
                'btn-danger': !this.state.connected})}
              onClick={this.toggleOnlineState}>
              {this.state.connected ? 'online' : 'offline'}
            </button>
          </div>
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
