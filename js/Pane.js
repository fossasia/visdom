/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import AbstractPropertiesList from './AbstractPropertiesList';
var classNames = require('classnames');

class Pane extends React.Component {
  _windowRef = null;
  _barRef = null;

  constructor(props) {
    super(props);
    this.state = {
      propertyListShown: false,
    };
  }

  close = () => {
    this.props.onClose(this.props.id);
  };

  focus = () => {
    this.props.onFocus(this.props.id);
  };

  download = () => {
    if (this.props.handleDownload) {
      this.props.handleDownload();
    }
  };

  togglePropertyList = () => {
    this.setState((state) => ({ propertyListShown: !state.propertyListShown }));
  };

  reset = () => {
    if (this.props.handleReset) {
      this.props.handleReset();
    }
  };

  zoom = (ev) => {
    if (this.props.handleZoom) {
      this.props.handleZoom(ev);
    }
  };

  over = (ev) => {
    if (this.props.handleMouseMove) {
      this.props.handleMouseMove(ev);
    }
  };

  resize = () => {
    if (this.props.resize) {
      this.props.onResize();
    }
  };

  getWindowSize = () => {
    return {
      h: this._windowRef.clientHeight,
      w: this._windowRef.clientWidth,
    };
  };

  getContentSize = () => {
    return {
      h: this._windowRef.clientHeight - this._barRef.scrollHeight,
      w: this._windowRef.clientWidth,
    };
  };

  shouldComponentUpdate(nextProps, nextState) {
    if (this.props.contentID !== nextProps.contentID) {
      return true;
    } else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    } else if (this.props.children !== nextProps.children) {
      return true;
    } else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    } else if (this.state.propertyListShown !== nextState.propertyListShown) {
      return true;
    }

    return false;
  }

  render() {
    let windowClassNames = classNames({
      window: true,
      focus: this.props.isFocused,
    });

    let barClassNames = classNames({
      bar: true,
      focus: this.props.isFocused,
    });

    let barwidgets = [];

    if (
      this.props.enablePropertyList &&
      this.props.content &&
      typeof this.props.content == 'object' &&
      this.props.content.data
    ) {
      barwidgets.push(
        <button
          key="properties-widget-button"
          title="properties"
          onClick={this.togglePropertyList}
          className={
            this.state.propertyListShown ? 'pull-right active' : 'pull-right'
          }
        >
          <span className="glyphicon glyphicon-tags" />
        </button>
      );
    }

    if (this.props.barwidgets) {
      if (Array.isArray(this.props.barwidgets))
        barwidgets = barwidgets.concat(this.props.barwidgets);
      else barwidgets.push(this.props.barwidgets);
    }

    return (
      <div
        className={windowClassNames}
        onClick={this.focus}
        onDoubleClick={this.reset}
        onWheel={this.zoom}
        onMouseMove={this.over}
        ref={(ref) => (this._windowRef = ref)}
      >
        <div className={barClassNames} ref={(ref) => (this._barRef = ref)}>
          <button title="close" onClick={this.close}>
            X
          </button>
          <button title="save" onClick={this.download}>
            &#8681;
          </button>
          <button
            title="reset"
            onClick={this.reset}
            hidden={!this.props.handleReset}
          >
            &#10226;
          </button>
          {barwidgets}
          <div>{this.props.title}</div>
        </div>
        <div className="content">{this.props.children}</div>
        <div className="widgets">{this.props.widgets}</div>
        {this.state.propertyListShown && (
          <div className="attachedWindow">
            {this.props.content.data.map((data, dataId) => [
              <b>Data[{dataId}] Properties</b>,
              <PropertyList
                keylist={'data[' + dataId + ']'}
                content={data}
                title={'Data[' + dataId + ']'}
              />,
              <hr />,
            ])}
            <b>Layout Properties</b>
            <PropertyList
              keylist="layout"
              content={this.props.content.layout}
              title="Layout"
            />
          </div>
        )}
      </div>
    );
  }
}

class PropertyList extends AbstractPropertiesList {
  _windowRef = null;
  _barRef = null;

  // updates the property of the window dynamically
  // note: this.props refers in this content to the Components directly responsible
  //       to the key, e.g. EditablePropertyText object from AbstractPropertiesList
  updateValue = (key, value) => {
    this.props.content[key] = value;
  };

  render() {
    // create for each element of props.content a representation in the PropertyList
    let props = Object.entries(this.props.content).map(([key_local, value]) => {
      // append key for multi-level objects
      var keylist = this.props.keylist
        ? Array.isArray(this.props.keylist)
          ? this.props.keylist.concat([key_local])
          : [this.props.keylist, key_local]
        : [key_local];
      var key_string =
        keylist.length > 1 ? keylist.slice(1).join('.') : keylist[0];

      // map value type to property type
      if (typeof value == 'number') var type = 'number';
      else if (typeof value == 'boolean') var type = 'checkbox';
      else if (typeof value == 'string') var type = 'text';
      else if (Array.isArray(value)) return [];
      else if (value && typeof value === 'object')
        return <PropertyList content={value} keylist={keylist} />;
      else return [];

      // list new property as part of a table
      return (
        <tr key={key_string}>
          <td className="table-properties-name">{key_string}</td>
          <td className="table-properties-value">
            {this.renderPropertyValue(
              {
                name: key_string,
                type: type,
                value: value,
              },
              key_local
            )}
          </td>
        </tr>
      );
    });

    // only first PropertyList in recursion should create a table-tag
    if (!Array.isArray(this.props.keylist))
      return (
        <table className="table table-bordered table-condensed table-properties">
          {props}
        </table>
      );
    else return props;
  }
}

export default Pane;
