/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { forwardRef, useRef, useState } from 'react';

import PropertyItem from './PropertyItem';
var classNames = require('classnames');

var Pane = forwardRef((props, ref) => {
  const { id, title, content, children, widgets, enablePropertyList } = props;
  var { barwidgets } = props;

  // state varibles
  // --------------
  const [propertyListShown, setPropertyListShown] = useState(false);
  const barRef = useRef();

  // public events
  // -------------
  const handleOnFocus = props.handleOnFocus || (() => props.onFocus(id));
  const handleDownload = props.handleDownload || (() => {});
  const handleReset = props.handleReset || (() => {});
  const handleZoom = props.handleZoom || ((ev) => {});
  const handleMouseMove = props.handleMouseMove || ((ev) => {});
  const handleClose = props.handleClose || (() => props.onClose(id));

  // rendering
  // ---------
  let windowClassNames = classNames({ window: true, focus: props.isFocused });
  let barClassNames = classNames({ bar: true, focus: props.isFocused });

  // add property list button to barwidgets
  if (
    enablePropertyList &&
    content &&
    typeof content == 'object' &&
    content.data
  ) {
    barwidgets = [
      ...barwidgets,
      <button
        key="properties-widget-button"
        title="properties"
        onClick={() => {
          setPropertyListShown(!propertyListShown);
        }}
        className={propertyListShown ? 'pull-right active' : 'pull-right'}
      >
        <span className="glyphicon glyphicon-tags" />
      </button>,
    ];
  }

  // render content.data & content.layout as property list
  let propertyListOverlay = '';
  if (propertyListShown && typeof content == 'object') {
    let propertylists = [];

    // properties for content.data
    if (typeof content.data == 'object') {
      propertylists = propertylists.concat(
        content.data.map((data, dataId) => [
          <span key={dataId}>
            <b>Data[{dataId}] Properties</b>
            <PropertyList
              keylist={'data[' + dataId + ']'}
              content={data}
              title={'Data[' + dataId + ']'}
            />
            <hr />
          </span>,
        ])
      );
    }

    // properties for content.data
    if (typeof content.layout == 'object') {
      propertylists.push(
        <span key="layout">
          <b>Layout Properties</b>
          <PropertyList
            keylist="layout"
            content={content.layout}
            title="Layout"
          />
        </span>
      );
    }

    propertyListOverlay = <div className="attachedWindow">{propertylists}</div>;
  }

  return (
    <div
      className={windowClassNames}
      onClick={handleOnFocus}
      onDoubleClick={handleReset}
      onWheel={handleZoom}
      onMouseMove={handleMouseMove}
      ref={ref}
    >
      <div className={barClassNames} ref={barRef}>
        <button title="close" onClick={handleClose}>
          {' '}
          X{' '}
        </button>
        <button title="save" onClick={handleDownload}>
          {' '}
          &#8681;{' '}
        </button>
        <button title="reset" onClick={handleReset} hidden={!props.handleReset}>
          {' '}
          &#10226;{' '}
        </button>
        {barwidgets}
        <div className="pull-right">{title}</div>
      </div>
      <div className="content">{children}</div>
      <div className="widgets">{widgets}</div>
      {propertyListOverlay}
    </div>
  );
});

// prevent rerender unless we know we need one
// (previously known as shouldComponentUpdate)
Pane = React.memo(Pane, (props, nextProps) => {
  if (props.contentID !== nextProps.contentID) return false;
  else if (props.h !== nextProps.h || props.w !== nextProps.w) return false;
  else if (props.children !== nextProps.children) return false;
  else if (props.isFocused !== nextProps.isFocused) return false;
  return true;
});

// this component is an overlay containing a property list (specialized for Pane)
function PropertyList(props) {
  const { keylist } = props;
  var { content } = props;

  // private events
  // --------------

  // updates the property of the window dynamically
  // note: props refers in this content to the Components directly responsible
  //       to the key, e.g. EditablePropertyText object from PropertyItem
  const updateValue = (key, value) => {
    content[key] = value;
  };

  // rendering
  // ---------

  // create for each element of content a representation in the PropertyList
  let propitems = Object.entries(content).map(([key_local, value]) => {
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
