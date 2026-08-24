/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

export default function serverPath() {
  var pathname = window.location.pathname;
  if (pathname.indexOf('/env/') > -1) {
    pathname = pathname.split('/env/')[0];
  } else if (pathname.indexOf('/compare/') > -1) {
    pathname = pathname.split('/compare/')[0];
  }
  if (pathname.slice(-1) != '/') {
    pathname = pathname + '/';
  }
  return pathname;
}
