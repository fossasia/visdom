/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useState, useEffect, useRef } from 'react';

function EditablePropertyText(props) {
  const textInput = useRef();
  const [actualValue, setActualValue] = useState(props.value);
  const [isEdited, setIsEdited] = useState(false);

  // update the state to current input value (rejects events based on validateHandler)
  const handleChange =
    props.handleChange ||
    (event => {
      let newValue = event.target.value;
      if (props.validateHandler && !props.validateHandler(newValue))
        event.preventDefault();
      else setActualValue(newValue);
    });

  // focus / blur toggles edit mode & blur saves the state
  const onFocus =
    props.onFocus ||
    (event => {
      setIsEdited(true);
    });
  const onBlur =
    props.onBlur ||
    (event => {
      setIsEdited(false);
      if (props.submitHandler) props.submitHandler(actualValue);

      // prevents the pane to drop focus
      // otherwise the sendPaneMessage-API does not work
      event.stopPropagation();
    });

  // Enter invokes blur and thus submits the change
  const handleKeyPress =
    props.handleKeyPress ||
    (event => {
      if (event.key === 'Enter') textInput.current.blur();
    });

  // adapt state if props changed & we are not in edit mode
  useEffect(() => {
    if (!isEdited) setActualValue(props.value);
  }, [props.value]);

  return (
    <input
      type="text"
      ref={textInput}
      value={actualValue}
      onChange={handleChange}
      onKeyPress={handleKeyPress}
      onBlur={onBlur}
      onFocus={onFocus}
    />
  );
}

class PropertiesItem extends React.Component {
  updateValue = (propId, value) => {};

  renderPropertyValue = (prop, propId) => {
    switch (prop.type) {
      case 'text':
        return (
          <EditablePropertyText
            value={prop.value}
            submitHandler={(value) => this.updateValue(propId, value)}
          />
        );
      case 'number':
        return (
          <EditablePropertyText
            value={prop.value}
            submitHandler={(value) => this.updateValue(propId, value)}
            validateHandler={(value) => value.match(/^[0-9]*([.][0-9]*)?$/i)}
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
            onChange={(event) => this.updateValue(propId, event.target.value)}
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

export default AbstractPropertiesList;
