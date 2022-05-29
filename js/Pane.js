/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useState, useRef, forwardRef } from 'react';
import PropertyItem from './PropertyItem';
var classNames = require('classnames');

var Pane = forwardRef((props, ref) => {
  const [propertyListShown, setPropertyListShown] = useState(false);
  const barRef = useRef();

  const togglePropertyList =
    props.togglePropertyList ||
    (() => {
      setPropertyListShown(!propertyListShown);
    });

  const handleDownload = props.handleDownload || (() => {});
  const handleReset = props.handleReset || (() => {});
  const handleZoom = props.handleZoom || ((ev) => {});
  const handleMouseMove = props.handleMouseMove || ((ev) => {});

  let windowClassNames = classNames({
    window: true,
    focus: props.isFocused,
  });

  let barClassNames = classNames({
    bar: true,
    focus: props.isFocused,
  });

  let barwidgets = [];

  if (
    props.enablePropertyList &&
    props.content &&
    typeof props.content == 'object' &&
    props.content.data
  ) {
    barwidgets.push(
      <button
        key="properties-widget-button"
        title="properties"
        onClick={togglePropertyList}
        className={propertyListShown ? 'pull-right active' : 'pull-right'}
      >
        <span className="glyphicon glyphicon-tags" />
      </button>
    );
  }

  if (props.barwidgets) {
    if (Array.isArray(props.barwidgets))
      barwidgets = barwidgets.concat(props.barwidgets);
    else barwidgets.push(props.barwidgets);
  }

  return (
    <div
      className={windowClassNames}
      onClick={() => props.onFocus(props.id)}
      onDoubleClick={handleReset}
      onWheel={handleZoom}
      onMouseMove={handleMouseMove}
      ref={ref}
    >
      <div className={barClassNames} ref={barRef}>
        <button title="close" onClick={() => props.onClose(props.id)}>
          X
        </button>
        <button title="save" onClick={handleDownload}>
          &#8681;
        </button>
        <button title="reset" onClick={handleReset} hidden={!props.handleReset}>
          &#10226;
        </button>
        {barwidgets}
        <div>{props.title}</div>
      </div>
      <div className="content">{props.children}</div>
      <div className="widgets">{props.widgets}</div>
      {propertyListShown && (
        <div className="attachedWindow">
          {props.content.data.map((data, dataId) => [
            <span key={dataId}>
              <b>Data[{dataId}] Properties</b>,
              <PropertyList
                keylist={'data[' + dataId + ']'}
                content={data}
                title={'Data[' + dataId + ']'}
              />
              ,
              <hr />,
            </span>,
          ])}
          <b>Layout Properties</b>
          <PropertyList
            keylist="layout"
            content={props.content.layout}
            title="Layout"
          />
        </div>
      )}
    </div>
  );
});

// previously known as shouldComponentUpdate
Pane = React.memo(Pane, (props, nextProps) => {
  if (props.contentID !== nextProps.contentID) return false;
  else if (props.h !== nextProps.h || props.w !== nextProps.w) return false;
  else if (props.children !== nextProps.children) return false;
  else if (props.isFocused !== nextProps.isFocused) return false;
  return true;
});

function PropertyList(props) {
  // updates the property of the window dynamically
  // note: props refers in this content to the Components directly responsible
  //       to the key, e.g. EditablePropertyText object from PropertyItem
  const updateValue =
    props.updateValue ||
    ((key, value) => {
      props.content[key] = value;
    });

  // create for each element of props.content a representation in the PropertyList
  let propitems = Object.entries(props.content).map(([key_local, value]) => {
    // append key for multi-level objects
    var keylist = props.keylist
      ? Array.isArray(props.keylist)
        ? props.keylist.concat([key_local])
        : [props.keylist, key_local]
      : [key_local];
    var key_string =
      keylist.length > 1 ? keylist.slice(1).join('.') : keylist[0];

    // map value type to property type
    if (typeof value == 'number') var type = 'number';
    else if (typeof value == 'boolean') var type = 'checkbox';
    else if (typeof value == 'string') var type = 'text';
    else if (Array.isArray(value)) return [];
    else if (value && typeof value === 'object')
      return (
        <PropertyList key={key_string} content={value} keylist={keylist} />
      );
    else return [];

    // list new property as part of a table
    return (
      <tr key={key_string}>
        <td className="table-properties-name">{key_string}</td>
        <td className="table-properties-value">
          <PropertyItem
            name={key_string}
            type={type}
            value={value}
            propId={key_local}
            updateValue={updateValue}
          />
        </td>
      </tr>
    );
  });

  // only first PropertyList in recursion should create a table-tag
  if (!Array.isArray(props.keylist))
    return (
      <table className="table table-bordered table-condensed table-properties">
        <tbody>{propitems}</tbody>
      </table>
    );
  else return propitems;
}

export default Pane;
