/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import React from 'react';

function WorkspaceBadge(props) {
  const { slug } = props;

  if (!slug) return null;

  return (
    <a
      className="btn btn-default"
      href="/"
      title={`Workspace "${slug}", back to the console`}
    >
      {slug}
    </a>
  );
}

export default WorkspaceBadge;
