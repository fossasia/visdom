import EmbeddingsPane from './panes/EmbeddingsPane';
import HParamsPane from './panes/HParamsPane';
import ImageComparePane from './panes/ImageComparePane';
import ImagePane from './panes/ImagePane';
import NetworkPane from './panes/NetworkPane';
import PlotPane from './panes/PlotPane';
import PropertiesPane from './panes/PropertiesPane';
import TablePane from './panes/TablePane';
import TextPane from './panes/TextPane';

const ROW_HEIGHT = 5; // pixels
const MARGIN = 10; // pixels
const DEFAULT_LAYOUT = 'current';
const PANES = {
  image: ImagePane,
  image_history: ImagePane,
  image_compare: ImageComparePane,
  plot: PlotPane,
  plot_history: PlotPane,
  text: TextPane,
  properties: PropertiesPane,
  table: TablePane,
  embeddings: EmbeddingsPane,
  network: NetworkPane,
  hparams: HParamsPane,
};
const PANE_SIZE = {
  image: [20, 20],
  image_history: [20, 20],
  image_compare: [40, 20],
  plot: [30, 24],
  plot_history: [30, 24],
  text: [20, 20],
  embeddings: [20, 20],
  properties: [20, 20],
  table: [30, 20],
  network: [20, 20],
  hparams: [98, 46],
};
const MODAL_STYLE = {
  content: {
    top: '50%',
    left: '50%',
    right: 'auto',
    bottom: 'auto',
    marginRight: '-50%',
    transform: 'translate(-50%, -50%)',
  },
};
const POLLING_INTERVAL = 500;

export {
  DEFAULT_LAYOUT,
  MARGIN,
  MODAL_STYLE,
  PANE_SIZE,
  PANES,
  POLLING_INTERVAL,
  ROW_HEIGHT,
};
