import React, { useContext, useEffect, useRef, useState } from 'react';

import ApiContext from './api/ApiContext';

const buildDimensions = (experiments) => {
  const dimensions = [
    {
      key: 'learning_rate',
      label: 'Learning Rate',
    },
    {
      key: 'batch_size',
      label: 'Batch Size',
    },
    {
      key: 'accuracy',
      label: 'Accuracy',
    },
  ];

  // Show loss when it is available, but keep the required starter dimensions.
  if (experiments.some((experiment) => experiment.loss != null)) {
    dimensions.push({
      key: 'loss',
      label: 'Loss',
    });
  }

  return dimensions.map((dimension) => ({
    label: dimension.label,
    values: experiments.map((experiment) => experiment[dimension.key]),
  }));
};

const ExperimentVisualization = ({ envIDs }) => {
  const { fetchParallelExperimentData } = useContext(ApiContext);
  const plotRef = useRef(null);
  const plotIdRef = useRef(
    'experiment-visualization-' + Math.random().toString(36).slice(2)
  );
  const envKey = envIDs.join(',');
  const [experiments, setExperiments] = useState([]);
  const [status, setStatus] = useState({
    loading: true,
    error: '',
  });

  useEffect(() => {
    let cancelled = false;

    const loadData = async () => {
      setStatus({
        loading: true,
        error: '',
      });

      try {
        const result = await fetchParallelExperimentData(envIDs);
        if (!cancelled) {
          setExperiments(result.experiments || []);
          setStatus({
            loading: false,
            error: '',
          });
        }
      } catch (error) {
        if (!cancelled) {
          setExperiments([]);
          setStatus({
            loading: false,
            error: error.message || 'Failed to load experiment visualization',
          });
        }
      }
    };

    loadData();

    return () => {
      cancelled = true;
    };
  }, [envKey]);

  useEffect(() => {
    if (!plotRef.current) {
      return;
    }

    if (experiments.length === 0) {
      Plotly.purge(plotRef.current);
      return;
    }

    Plotly.react(
      plotIdRef.current,
      [
        {
          type: 'parcoords',
          line: {
            color: experiments.map((experiment) => experiment.accuracy),
            colorscale: 'Viridis',
            showscale: true,
          },
          dimensions: buildDimensions(experiments),
        },
      ],
      {
        margin: { l: 50, r: 50, t: 20, b: 20 },
      },
      {
        responsive: true,
      }
    );
  }, [experiments]);

  return (
    <div
      style={{
        margin: '10px',
        padding: '12px',
        background: '#fff',
        border: '1px solid #ddd',
      }}
    >
      <h4 style={{ marginTop: 0 }}>Experiment Visualization</h4>
      {status.loading ? <div>Loading experiment data...</div> : null}
      {!status.loading && status.error ? <div>{status.error}</div> : null}
      {!status.loading && !status.error && experiments.length === 0 ? (
        <div>
          No experiment metadata found. Add numeric `learning_rate`,
          `batch_size`, and `accuracy` properties to an environment to render
          this plot.
        </div>
      ) : null}
      <div
        id={plotIdRef.current}
        ref={plotRef}
        style={{
          display:
            !status.loading && !status.error && experiments.length > 0
              ? 'block'
              : 'none',
          width: '100%',
          height: '420px',
        }}
      />
    </div>
  );
};

export default ExperimentVisualization;
