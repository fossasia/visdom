/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useState } from 'react';

import ApiContext from '../api/ApiContext';
import Pane from './Pane';
import PropertyItem from './PropertyItem';

function PropertiesPane(props) {
  const { sendPaneMessage } = useContext(ApiContext);
  const { envID, id, content, onFocus } = props;
  
  console.log('🔄 PropertiesPane rendering');
  console.log('📦 Received content prop:', content);
  
  const [localContent, setLocalContent] = useState(content);
  
  useEffect(() => {
    console.log('📥 useEffect triggered - content changed!');
    console.log('Old content:', localContent);
    console.log('New content:', content);
    setLocalContent(content);
  }, [content]);
  
  useEffect(() => {
    console.log('🎨 localContent state updated:', localContent);
  }, [localContent]);

  const updateValue = (propId, value) => {
    console.log('✏️ Updating property:', propId, value);
    onFocus(id, () => {
      sendPaneMessage(
        {
          event_type: 'PropertyUpdate',
          propertyId: propId,
          value: value,
        },
        id,
        envID
      );
    });
  };

  const handleDownload = () => {
    console.log('💾 Downloading properties:', localContent);
    let blob = new Blob([JSON.stringify(localContent)], {
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
          <tbody>
            {localContent.map((prop, propId) => (
              <tr key={propId}>
                <td className="table-properties-name">{prop.name}</td>
                <td className="table-properties-value">
                  <PropertyItem
                    {...prop}
                    propId={propId}
                    updateValue={updateValue}
                    blurStopPropagation={true}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Pane>
  );
}

export default PropertiesPane;