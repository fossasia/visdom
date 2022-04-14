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
import Pane from './Pane';

class PropertiesPane extends AbstractPropertiesList {
  updateValue = (propId, value) => {
    this.props.onFocus(this.props.id, () => {
      this.props.appApi.sendPaneMessage({
        event_type: 'PropertyUpdate',
        propertyId: propId,
        value: value,
      });
    });
  };

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

export default PropertiesPane;
