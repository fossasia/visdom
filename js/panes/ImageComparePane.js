/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

import Pane from './Pane';

function ImageComparePane(props) {
  const { content, title, id } = props;

  // If content isn't an array, fallback
  if (!Array.isArray(content)) {
    return <Pane {...props}>Invalid Image Data</Pane>;
  }

  const handleDownload = () => {
    content.forEach((img, index) => {
      let link = document.createElement('a');
      
      // Safely extract extension from data URI, default to png
      var match = img.src.match(/data:image\/([a-zA-Z]+);/);
      var ext = (match && match[1]) ? match[1] : 'png';
      if (ext === 'jpeg') ext = 'jpg';

      let filenameSuffix = content.length > 1 ? `_${index + 1}` : '';
      link.download = `${title || 'visdom_compare'}${filenameSuffix}.${ext}`;
      
      link.href = img.src;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    });
  };

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          width: '100%',
          height: '100%',
          overflowX: 'auto',
          alignItems: 'center',
          justifyContent: 'space-around'
        }}
      >
        {content.map((imgItem, idx) => (
          <div
             key={`${id}-compare-${idx}`}
             style={{
               flex: 1,
               display: 'flex',
               flexDirection: 'column',
               alignItems: 'center',
               padding: '5px'
             }}
          >
      {/* Only show the legend if there are multiple images being compared */}
            {content.length > 1 && imgItem.caption && (
               <span
                 className="widget"
                 style={{
                   marginBottom: '5px',
                   fontWeight: 'bold'
                 }}
               >
                 {imgItem.caption}
               </span>
            )}
            <img
              className="content-image"
              alt={imgItem.caption || 'Compare Image'}
              src={imgItem.src}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain'
              }}
            />
          </div>
        ))}
      </div>
    </Pane>
  );
}

export default ImageComparePane;
