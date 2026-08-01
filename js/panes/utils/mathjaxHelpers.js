/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

function typesetMathJax(element, isCancelled) {
  if (!element) return;
  if (
    !window.MathJax ||
    !window.MathJax.startup ||
    !window.MathJax.startup.promise
  ) {
    return;
  }
  window.MathJax.startup.promise = window.MathJax.startup.promise
    .then(() => {
      if (isCancelled && isCancelled()) return;
      return window.MathJax.typesetPromise([element]);
    })
    .catch((err) => {
      console.error('MathJax typeset error:', err);
    });
}

export { typesetMathJax };
