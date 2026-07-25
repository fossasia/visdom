/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { useMemo } from 'react';

import { buildColumns } from './hparamsUtils';

export default function useHParamsColumns(paramKeys, metricKeys, tagKeys) {
  return useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
}
