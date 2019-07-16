/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import EventSystem from './EventSystem';
const Pane = require('./Pane');

class ImagePane extends React.Component {
  _paneRef = null;

  state = {
    scale: 1,
    tx: 0,
    ty: 0,
    selected: this.props.selected,
    mouse_location: { x: 0, y: 0, visibility: 'hidden' },
  };

  drag_start_x = null;
  drag_start_y = null;

  componentWillReceiveProps = nextProps => {
    if (nextProps.selected !== this.props.selected) {
      this.setState({ selected: nextProps.selected });
    }
  };

  onEvent = event => {
    if (!this.props.isFocused) {
      return;
    }

    switch (event.type) {
      case 'keydown':
      case 'keypress':
        event.preventDefault();
        break;
      case 'keyup':
        this.props.appApi.sendPaneMessage({
          event_type: 'KeyPress',
          key: event.key,
          key_code: event.keyCode,
        });
        break;
      case 'click':
        this.props.appApi.sendPaneMessage({
          event_type: 'Click',
          image_coord: this.state.mouse_location,
        });
        break;
    }
  };

  componentDidMount() {
    EventSystem.subscribe('global.event', this.onEvent);
  }

  componentWillUnmount() {
    EventSystem.unsubscribe('global.event', this.onEvent);
  }

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_image'}.jpg`;
    link.href = this.props.content.src;
    link.click();
  };

  handleZoom = ev => {
    if (ev.altKey) {
      //var direction = natural.checked ? -1 : 1;
      let direction = -1;
      // Get browser independent scaling factor
      let scrollDirectionX = Math.sign(ev.deltaX);
      let scrollDirectionY = Math.sign(ev.deltaY);
      // If shift is pressed only scroll sidewise (to allow scrolling
      // to the side by keep shift pressed and using normal scrolling
      // on the image pane)
      if (ev.shiftKey) {
        this.setState({
          tx: this.state.tx + scrollDirectionY * direction * 50,
        });
      } else {
        this.setState({
          tx: this.state.tx + scrollDirectionX * direction * 50,
        });
        this.setState({
          ty: this.state.ty + scrollDirectionY * direction * 50,
        });
      }
      ev.stopPropagation();
      ev.preventDefault();
    } else if (ev.ctrlKey) {
      // get the x and y offset of the pane
      let rect = this._paneRef._windowRef.children[1].getBoundingClientRect();
      // Get browser independent scaling factor
      let scrollDirectionY = Math.sign(ev.deltaY);
      // Compute the coords of the mouse relative to the top left of the pane
      let xscreen = ev.clientX - rect.x;
      let yscreen = ev.clientY - rect.y;
      // Compute the coords of the pixel under the mouse wrt the image top left
      let ximage = (xscreen - this.state.tx) / this.state.scale;
      let yimage = (yscreen - this.state.ty) / this.state.scale;
      let new_scale = this.state.scale * Math.exp(-scrollDirectionY / 10);
      // Update the state.
      // The offset is modifed such that the pixel under the mouse
      // is the same after zooming
      this.setState({
        scale: new_scale,
        tx: xscreen - new_scale * ximage,
        ty: yscreen - new_scale * yimage,
      });
      ev.stopPropagation();
      ev.preventDefault();
    }
  };

  handleDragStart = ev => {
    this.drag_start_x = ev.screenX;
    this.drag_start_y = ev.screenY;
  };

  handleDragOver = ev => {
    this.setState({
      tx: this.state.tx + ev.screenX - this.drag_start_x,
      ty: this.state.ty + ev.screenY - this.drag_start_y,
    });
    this.drag_start_x = ev.screenX;
    this.drag_start_y = ev.screenY;
  };

  handleMouseOver = ev => {
    // get the x and y offset of the pane
    var rect = this._paneRef._windowRef.children[1].getBoundingClientRect();
    // Compute the coords of the mouse relative to the top left of the pane
    var xscreen = ev.clientX - rect.x;
    var yscreen = ev.clientY - rect.y;
    // Compute the coords of the pixel under the mouse wrt the image top left
    var ximage = Math.round((xscreen - this.state.tx) / this.state.scale);
    var yimage = Math.round((yscreen - this.state.ty) / this.state.scale);
    this.setState({
      mouse_location: {
        x: ximage,
        y: yimage,
        visibility: ev.altKey ? 'visible' : 'hidden',
      },
    });
  };

  handleReset = () => {
    this.setState({
      scale: 1,
      tx: 0,
      ty: 0,
    });
  };

  updateSlider = evt => {
    // TODO add history update events here! need to send these to the client
    // with sendPaneMessage
    this.setState({
      selected: evt.target.value,
    });
  };

  render() {
    let content = this.props.content;
    let type = this.props.type;
    let widgets = [];

    if (type === 'image_history') {
      let selected = this.state.selected;
      if (this.props.show_slider) {
        widgets.push(
          <div className="widget">
            <div style={{ display: 'flex' }}>
              <span>Selected:&nbsp;&nbsp;</span>
              <input
                type="range"
                min="0"
                max={content.length - 1}
                value={this.state.selected}
                onInput={this.updateSlider.bind(this)}
              />
              <span>&nbsp;&nbsp;{this.state.selected}&nbsp;&nbsp;</span>
            </div>
          </div>
        );
      }
      content = content[selected];
    }

    if (content.caption) {
      widgets.splice(0, 0, <span className="widget">{content.caption}</span>);
    }

    // TODO use this widget_height somehow to adjust window height!!!
    let widget_height = 30 * widgets.length - 10;

    const divstyle = {
      left: this.state.tx,
      top: this.state.ty,
      position: 'absolute',
    };

    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        handleReset={this.handleReset.bind(this)}
        handleZoom={this.handleZoom.bind(this)}
        handleMouseMove={this.handleMouseOver.bind(this)}
        ref={ref => (this._paneRef = ref)}
        widgets={widgets}
      >
        >
        <div style={divstyle}>
          <img
            className="content-image cssTransforms"
            src={content.src}
            width={Math.ceil(1 + this.props.width * this.state.scale) + 'px'}
            height={Math.ceil(1 + this.props.height * this.state.scale) + 'px'}
            onDoubleClick={this.handleReset.bind(this)}
            onDragStart={this.handleDragStart.bind(this)}
            onDragOver={this.handleDragOver.bind(this)}
          />
        </div>
        <p className="caption">{content.caption}</p>
        <span
          className="mouse_image_location"
          style={{ visibility: this.state.mouse_location.visibility }}
        >
          {this.state.mouse_location.x + ' / ' + this.state.mouse_location.y}
        </span>
      </Pane>
    );
  }
}

module.exports = ImagePane;
