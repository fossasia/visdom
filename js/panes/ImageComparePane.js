/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef } from 'react';

import { showToast } from '../toasts/toastEvents';
import Pane from './Pane';
import { copyLatexToClipboard } from './utils/LatexExport';
import { typesetMathJax } from './utils/mathjaxHelpers';

function ImageComparePane(props) {
  const { content, title, id, contentID } = props;
  const containerRef = useRef();

  useEffect(() => {
    let cancelled = false;
    typesetMathJax(containerRef.current, () => cancelled);
    return () => {
      cancelled = true;
    };
  }, [content]);

  // If content isn't an array, fallback
  if (!Array.isArray(content)) {
    return <Pane {...props}>Invalid Image Data</Pane>;
  }

  const handleDownload = () => {
    content.forEach((img, index) => {
      setTimeout(() => {
        let link = document.createElement('a');

        let filenameSuffix = content.length > 1 ? `_${index + 1}` : '';
        link.download = `${title || 'visdom_compare'}${filenameSuffix}.jpg`;

        link.href = img.src;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }, index * 300);
    });
  };

  const handleLatexExport = (style) => {
    const isSingleImage = content.length <= 1;
    copyLatexToClipboard(style, {
      contentID,
      id,
      caption: title || (isSingleImage ? content[0]?.caption : undefined),
      images: isSingleImage
        ? undefined
        : content.map((imgItem) => ({ caption: imgItem.caption })),
    })
      .then(() =>
        showToast('Copied!', 'success', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        })
      )
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('ImageComparePane LaTeX export failed:', err);
        showToast('Failed to Copy', 'error', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        });
      });
  };

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      handleLatexExport={handleLatexExport}
    >
      <div
        ref={containerRef}
        style={{
          display: 'flex',
          flexDirection: 'row',
          width: '100%',
          height: '100%',
          overflowX: 'auto',
          alignItems: 'stretch',
          justifyContent: 'space-around',
        }}
      >
        {content.map((imgItem, idx) => (
          <figure
            key={`${id}-compare-${idx}`}
            data-testid="compare-cell"
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              padding: '5px',
              minHeight: 0,
              margin: 0,
            }}
          >
            {/* Only show caption when comparing multiple images */}
            {content.length > 1 && imgItem.caption && (
              <figcaption
                className="widget"
                style={{
                  flexShrink: 0,
                  marginBottom: '5px',
                  fontWeight: 'bold',
                }}
              >
                {imgItem.caption}
              </figcaption>
            )}
            <div
              style={{
                flex: 1,
                minHeight: 0,
                position: 'relative',
                width: '100%',
              }}
            >
              <img
                className="content-image"
                alt={imgItem.caption || 'Compare Image'}
                src={imgItem.src}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                }}
              />
            </div>
          </figure>
        ))}
      </div>
    </Pane>
  );
}

export default ImageComparePane;
