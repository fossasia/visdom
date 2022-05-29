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
  // state varibles
  // --------------
  const textInput = useRef();
  const [actualValue, setActualValue] = useState(props.value);
  const [isEdited, setIsEdited] = useState(false);

  // private events
  // --------------

  // update the state to current input value (rejects events based on validateHandler)
  const handleChange = (event) => {
    let newValue = event.target.value;
    if (props.validateHandler && !props.validateHandler(newValue))
      event.preventDefault();
    else setActualValue(newValue);
  };

  // focus / blur toggles edit mode & blur saves the state
  const onFocus = (event) => {
    setIsEdited(true);
  };
  const onBlur = (event) => {
    setIsEdited(false);
    if (props.submitHandler) props.submitHandler(actualValue);

    // prevents the pane to drop focus
    // otherwise the sendPaneMessage-API does not work
    if (props.blurStopPropagation) event.stopPropagation();
  };

  // Enter invokes blur and thus submits the change
  const handleKeyPress = (event) => {
    if (event.key === 'Enter') textInput.current.blur();
  };

  // effects
  // -------

  // save value if props changed & we are not in edit mode
  useEffect(() => {
    if (!isEdited) setActualValue(props.value);
  }, [props.value]);

  // rendering
  // ---------

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

// this component abstracts several types of inputs (text, number, button, checkbox, select) to a common API
function PropertyItem(props) {
  // by default, this item has no real function and needs to be replaced when used
  const updateValue = props.updateValue || ((propId, value) => {});

  // rendering
  // ---------
  switch (props.type) {
    case 'text':
      return (
        <EditablePropertyText
          value={props.value}
          submitHandler={(value) => updateValue(props.propId, value)}
          blurStopPropagation={props.blurStopPropagation}
        />
      );
    case 'number':
      return (
        <EditablePropertyText
          value={props.value}
          submitHandler={(value) => updateValue(props.propId, value)}
          validateHandler={(value) => value.match(/^[0-9]*([.][0-9]*)?$/i)}
          blurStopPropagation={props.blurStopPropagation}
        />
      );
    case 'button':
      return (
        <button
          className="btn btn-sm"
          onClick={() => updateValue(props.propId, 'clicked')}
        >
          {props.value}
        </button>
      );
    case 'checkbox':
      return (
        <label className="checkbox-inline">
          <input
            type="checkbox"
            checked={props.value}
            onChange={() => updateValue(props.propId, !props.value)}
          />
          &nbsp;
        </label>
      );
    case 'select':
      return (
        <select
          className="form-control"
          onChange={(event) => updateValue(props.propId, event.target.value)}
          value={props.value}
        >
          {props.values.map((name, id) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      );
  }
}

export default PropertyItem;
