/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useRef } from 'react';

import Pane from './Pane';

function ImageComparePane(props) {
  const { content, title, id } = props;
  const paneRef = useRef();

  // If content isn't an array, fallback
  if (!Array.isArray(content)) {
    return <Pane {...props}>Invalid Image Data</Pane>;
  }

  const handleDownload = () => {
    // Download first image or combine them; simplified for now to first image
    if (content.length > 0) {
      let link = document.createElement('a');
      link.download = `${title || 'visdom_compare'}.jpg`;
      link.href = content[0].src;
      link.click();
    }
  };

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      ref={paneRef}
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
            {imgItem.caption && (
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