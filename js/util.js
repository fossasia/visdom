/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

/* global $ */

import { useEffect, useRef } from 'react';

const TOOLTIP_SELECTOR = '[data-toggle="tooltip"]';
const TOOLTIP_OPTIONS = {
  container: 'body',
  delay: {
    show: 600,
    hide: 100,
  },
  trigger: 'hover',
};

// custom hook to get previous value of a variable
function usePrevious(value) {
  const ref = useRef();
  useEffect(() => {
    ref.current = value;
  });
  return ref.current;
}

// custom hook to keep bootstrap tooltips in sync with the rendered markup
function useTooltips() {
  useEffect(() => {
    $(TOOLTIP_SELECTOR).each((_, el) => {
      const $tip = $(el);
      const title = $tip.attr('title');
      if (title) {
        $tip.attr('data-original-title', title).attr('title', '');
      }
      if (!$tip.data('bs.tooltip')) {
        $tip.tooltip(TOOLTIP_OPTIONS);
      }
    });
  });
}

function destroyTooltips() {
  $(TOOLTIP_SELECTOR).tooltip('destroy');
}

export { destroyTooltips, usePrevious, useTooltips };
