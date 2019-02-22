/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
const Pane = require('./Pane');

class MyRef {
  constructor() {
    this._ref = null;
  }

  getRef() {
    return this._ref;
  }

  setRef = ref => {
    this._ref = ref;
  };
}

class Text extends React.Component {
  constructor(props) {
    super(props);
    this.textInput = new MyRef();
    this.state = {
      propsValue: props.value,
      actualValue: props.value,
      isEdited: false,
    };
  }

  handleChange = event => {
    let newValue = event.target.value;
    if (this.props.validateHandler && !this.props.validateHandler(newValue)) {
      event.preventDefault();
    } else {
      this.setState({
        actualValue: newValue,
      });
    }
  };

  handleKeyPress = event => {
    if (event.key === 'Enter') {
      let ref = this.textInput.getRef();
      if (ref) ref.blur(); // Blur invokes submit
    }
  };

  onBlur = () => {
    this.setState({ isEdited: false }, () => {
      if (this.props.submitHandler) {
        this.props.submitHandler(this.state.actualValue);
      }
    });
  };

  onFocus = () => {
    this.setState({
      isEdited: true,
    });
  };

  UNSAFE_componentWillReceiveProps(nextProps) {
    if (this.state.propsValue !== nextProps.value || !this.state.isEdited) {
      let newState = this.state.isEdited
        ? {
            propsValue: nextProps.value,
          }
        : {
            propsValue: nextProps.value,
            actualValue: nextProps.value,
          };
      this.setState(newState);
    }
  }

  render() {
    return (
      <input
        type="text"
        ref={this.textInput.setRef}
        value={this.state.actualValue}
        onChange={this.handleChange}
        onKeyPress={this.handleKeyPress}
        onBlur={this.onBlur}
        onFocus={this.onFocus}
      />
    );
  }
}

class PropertiesPane extends React.Component {
  handleDownload = () => {
    var blob = new Blob([JSON.stringify(this.props.content)], {
      type: 'application/json',
    });
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.download = 'visdom_properties.json';
    link.href = url;
    link.click();
  };

  updateValue = (propId, value) => {
    this.props.onFocus(this.props.id, () => {
      this.props.appApi.sendPaneMessage({
        event_type: 'PropertyUpdate',
        propertyId: propId,
        value: value,
      });
    });
  };

  renderPropertyValue = (prop, propId) => {
    switch (prop.type) {
      case 'text':
        return (
          <Text
            value={prop.value}
            submitHandler={value => this.updateValue(propId, value)}
          />
        );
      case 'number':
        return (
          <Text
            value={prop.value}
            submitHandler={value => this.updateValue(propId, value)}
            validateHandler={value => value.match(/^[0-9]*([.][0-9]*)?$/i)}
          />
        );
      case 'button':
        return (
          <button
            className="btn btn-sm"
            onClick={() => this.updateValue(propId, 'clicked')}
          >
            {prop.value}
          </button>
        );
      case 'checkbox':
        return (
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={prop.value}
              onChange={() => this.updateValue(propId, !prop.value)}
            />
            &nbsp;
          </label>
        );
      case 'select':
        return (
          <select
            className="form-control"
            onChange={event => this.updateValue(propId, event.target.value)}
            value={prop.value}
          >
            {prop.values.map((name, id) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        );
    }
  };

  render() {
    return (
      <Pane {...this.props} handleDownload={this.handleDownload}>
        <div className="content-properties">
          <table className="table table-bordered table-condensed table-properties">
            {this.props.content.map((prop, propId) => (
              <tr key={propId}>
                <td className="table-properties-name">{prop.name}</td>
                <td className="table-properties-value">
                  {this.renderPropertyValue(prop, propId)}
                </td>
              </tr>
            ))}
          </table>
        </div>
      </Pane>
    );
  }
}

module.exports = PropertiesPane;
