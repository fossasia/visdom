/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import PropertyItem from './PropertyItem';
import Pane from './Pane';

function PropertiesPane(props) {
  // send updates in PropertyItem directly to all observers / sources
  const updateValue = (propId, value) => {
    props.onFocus(props.id, () => {
      props.appApi.sendPaneMessage({
        event_type: 'PropertyUpdate',
        propertyId: propId,
        value: value,
      });
    });
  };

  // download button saves the settings as json
  const handleDownload = () => {
    let blob = new Blob([JSON.stringify(props.content)], {
      type: 'application/json',
    });
    let url = window.URL.createObjectURL(blob);
    let link = document.createElement('a');
    link.download = 'visdom_properties.json';
    link.href = url;
    link.click();
  };

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <div className="content-properties">
        <table className="table table-bordered table-condensed table-properties">
          {props.content.map((prop, propId) => (
            <tr key={propId}>
              <td className="table-properties-name">{prop.name}</td>
              <td className="table-properties-value">
                <PropertyItem
                  {...prop}
                  propId={propId}
                  updateValue={updateValue}
                />
              </td>
            </tr>
          ))}
        </table>
      </div>
    </Pane>
  );
}

export default PropertiesPane;
