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

function readContent(content) {
  if (!content || typeof content !== 'object' || Array.isArray(content)) {
    return null;
  }
  if (!Array.isArray(content.records)) {
    return null;
  }
  const asKeys = (value) => (Array.isArray(value) ? value : []);
  return {
    records: content.records,
    paramKeys: asKeys(content.param_keys),
    metricKeys: asKeys(content.metric_keys),
    tagKeys: asKeys(content.tag_keys),
  };
}

var HParamsPane = (props) => {
  const { content } = props;
  const data = readContent(content);

  const handleDownload = () => {
    let blob = new Blob([JSON.stringify(content)], {
      type: 'application/json',
    });
    let url = window.URL.createObjectURL(blob);
    let link = document.createElement('a');
    link.download = 'visdom_hparams.json';
    link.href = url;
    link.click();
  };

  let body;
  if (data === null) {
    body = (
      <div className="hparams-message hparams-error">
        Could not read hyper-parameter data for this window.
      </div>
    );
  } else if (data.records.length === 0) {
    body = (
      <div className="hparams-message hparams-empty">
        No experiments match this selection.
      </div>
    );
  } else {
    body = (
      <div className="hparams-body">
        <div className="hparams-summary">
          <span className="hparams-stat">
            <b>{data.records.length}</b> runs
          </span>
          <span className="hparams-stat">
            <b>{data.paramKeys.length}</b> params
          </span>
          <span className="hparams-stat">
            <b>{data.metricKeys.length}</b> metrics
          </span>
          <span className="hparams-stat">
            <b>{data.tagKeys.length}</b> tags
          </span>
        </div>
        <ul className="hparams-runs">
          {data.records.map((record, index) => (
            <li className="hparams-run" key={record.env_id || index}>
              <span className="hparams-run-name">
                {record.name || record.env_id || 'run ' + index}
              </span>
              {record.status ? (
                <span
                  className={
                    'hparams-run-status hparams-status-' + record.status
                  }
                >
                  {record.status}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        <div className="hparams-views" />
      </div>
    );
  }

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <div className="content-hparams">{body}</div>
    </Pane>
  );
};

HParamsPane = React.memo(HParamsPane, (props, nextProps) => {
  if (props.contentID !== nextProps.contentID) return false;
  else if (props.h !== nextProps.h || props.w !== nextProps.w) return false;
  else if (props.isFocused !== nextProps.isFocused) return false;
  return true;
});

export default HParamsPane;
