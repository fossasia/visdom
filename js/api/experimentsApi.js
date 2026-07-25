import serverPath from './serverPath';

/**
 * Read the comparison payload for a set of runs.
 *
 * Deliberately window.fetch and not jQuery: ApiProvider installs a
 * document-level ajaxError handler that navigates the whole page to
 * error/500, so a 404 for a deleted run would destroy the dashboard.
 * fetch keeps the failure local to the caller.
 *
 * The response carries params/metrics/tags diff sections alongside the
 * raw experiments; only experiments[].metrics holds per-step history.
 */
export function fetchExperimentComparison(envIds, signal) {
  const ids = (envIds || []).filter((id) => typeof id === 'string');
  if (ids.length === 0) {
    return Promise.reject(new Error('No runs to load.'));
  }
  return window
    .fetch(serverPath() + 'experiments/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ env_ids: ids }),
      signal,
    })
    .catch((err) => {
      /* A dead server rejects with a bare "Failed to fetch", which reads
         like a bug rather than a server that is not answering. */
      if (err && err.name === 'AbortError') throw err;
      throw new Error('Could not reach the server.');
    })
    .then((res) => {
      /* An empty 401 body from check_auth would make res.json() throw a
         SyntaxError that reads like a parsing bug, so branch on ok first. */
      if (!res.ok) {
        const reason = res.statusText || 'request failed';
        throw new Error('Could not load metric history (' + reason + ').');
      }
      return res.json();
    });
}

export default fetchExperimentComparison;
