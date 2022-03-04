/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

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

class AbstractPropertiesList extends React.Component {
  updateValue = (propId, value) => {};

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
}

module.exports = AbstractPropertiesList;
