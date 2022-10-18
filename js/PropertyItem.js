/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';

function EditablePropertyText(props) {
  const { value, validateHandler, submitHandler, blurStopPropagation } = props;

  // state varibles
  // --------------
  const textInput = useRef();
  const [actualValue, setActualValue] = useState(value);
  const [isEdited, setIsEdited] = useState(false);

  // private events
  // --------------

  // update the state to current input value (rejects events based on validateHandler)
  const handleChange = (event) => {
    let newValue = event.target.value;
    if (validateHandler && !validateHandler(newValue)) event.preventDefault();
    else setActualValue(newValue);
  };

  // focus / blur toggles edit mode & blur saves the state
  const onFocus = (event) => {
    setIsEdited(true);
  };
  const onBlur = (event) => {
    setIsEdited(false);
    if (submitHandler) submitHandler(actualValue);

    // prevents the pane to drop focus
    // otherwise the sendPaneMessage-API does not work
    if (blurStopPropagation) event.stopPropagation();
  };

  // Enter invokes blur and thus submits the change
  const handleKeyPress = (event) => {
    if (event.key === 'Enter') textInput.current.blur();
  };

  // effects
  // -------

  // save value if props changed & we are not in edit mode
  useEffect(() => {
    if (!isEdited) setActualValue(value);
  }, [value]);

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
  const { propId, type, value, values, blurStopPropagation } = props;

  // by default, this item has no real function and needs to be replaced when used
  const updateValue = props.updateValue || ((propId, value) => {});

  // rendering
  // ---------
  switch (type) {
    case 'text':
      return (
        <EditablePropertyText
          value={value}
          submitHandler={(value) => updateValue(propId, value)}
          blurStopPropagation={blurStopPropagation}
        />
      );
    case 'number':
      return (
        <EditablePropertyText
          value={value}
          submitHandler={(value) => updateValue(propId, value)}
          validateHandler={(value) => value.match(/^[0-9]*([.][0-9]*)?$/i)}
          blurStopPropagation={blurStopPropagation}
        />
      );
    case 'button':
      return (
        <button
          className="btn btn-sm"
          onClick={() => updateValue(propId, 'clicked')}
        >
          {value}
        </button>
      );
    case 'checkbox':
      return (
        <label className="checkbox-inline">
          <input
            type="checkbox"
            checked={value}
            onChange={() => updateValue(propId, !value)}
          />
          &nbsp;
        </label>
      );
    case 'select':
      return (
        <select
          className="form-control"
          onChange={(event) => updateValue(propId, event.target.value)}
          value={value}
        >
          {values.map((name, id) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      );
  }
}

export default PropertyItem;
