/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchExperimentComparison } from '../../api/experimentsApi';
import { buildMetricSeries } from './hparamsUtils';

const NO_EXPERIMENTS = [];
const COMPARE_BATCH_SIZE = 1000;

function batchIds(ids) {
  const batches = [];
  for (let i = 0; i < ids.length; i += COMPARE_BATCH_SIZE) {
    batches.push(ids.slice(i, i + COMPARE_BATCH_SIZE));
  }
  return batches;
}

export default function useExperimentMetrics(records, cacheRef) {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState({
    status: 'idle',
    error: null,
    experiments: NO_EXPERIMENTS,
  });

  const envIds = useMemo(
    () => (records || []).map((r) => r.env_id).filter((id) => !!id),
    [records]
  );

  const refresh = useCallback(() => {
    const cache = cacheRef.current;
    if (cache) envIds.forEach((id) => cache.delete(id));
    setNonce((n) => n + 1);
  }, [cacheRef, envIds]);

  useEffect(() => {
    const cache = cacheRef.current;
    if (envIds.length === 0) {
      setState({ status: 'idle', error: null, experiments: NO_EXPERIMENTS });
      return undefined;
    }

    const readCache = () => envIds.map((id) => cache.get(id)).filter(Boolean);
    const wanted = envIds.filter((id) => !cache.has(id));
    if (wanted.length === 0) {
      setState({ status: 'ready', error: null, experiments: readCache() });
      return undefined;
    }

    let cancelled = false;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, status: 'loading', error: null }));

    Promise.all(
      batchIds(wanted).map((ids) =>
        fetchExperimentComparison(ids, controller.signal)
      )
    )
      .then((replies) => {
        if (cancelled) return;
        replies.forEach((reply) => {
          const loaded = (reply && reply.experiments) || [];
          loaded.forEach((exp) => {
            if (exp && typeof exp.env_id === 'string')
              cache.set(exp.env_id, exp);
          });
        });
        setState({ status: 'ready', error: null, experiments: readCache() });
      })
      .catch((err) => {
        if (cancelled || (err && err.name === 'AbortError')) return;
        setState({
          status: 'error',
          error: (err && err.message) || 'Could not load metric history.',
          experiments: NO_EXPERIMENTS,
        });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [envIds, nonce, cacheRef]);

  const parsed = useMemo(
    () => buildMetricSeries(state.experiments),
    [state.experiments]
  );

  return {
    status: state.status,
    error: state.error,
    runs: parsed.runs,
    metricKeys: parsed.metricKeys,
    refresh,
  };
}
