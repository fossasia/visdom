import EmbeddingsPane from './EmbeddingsPane';
import ImagePane from './ImagePane';
import NetworkPane from './NetworkPane';
import PlotPane from './PlotPane';
import PropertiesPane from './PropertiesPane';
import TextPane from './TextPane';

const ROW_HEIGHT = 5; // pixels
const MARGIN = 10; // pixels
const DEFAULT_LAYOUT = 'current';
const PANES = {
  image: ImagePane,
  image_history: ImagePane,
  plot: PlotPane,
  text: TextPane,
  properties: PropertiesPane,
  embeddings: EmbeddingsPane,
  network: NetworkPane,
};
const PANE_SIZE = {
  image: [20, 20],
  image_history: [20, 20],
  plot: [30, 24],
  text: [20, 20],
  embeddings: [20, 20],
  properties: [20, 20],
  network: [20, 20],
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
