/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import ReactDOM from 'react-dom';

const Width = (ComposedComponent) =>
  class Width extends React.Component {
    state = {
      width: 1280,
      cols: 100,
    };

    mounted = false;

    componentDidMount() {
      this.mounted = true;

      window.addEventListener('resize', this.onWindowResize);
      this.onWindowResize();
    }

    componentWillUnmount() {
      this.mounted = false;
      window.removeEventListener('resize', this.onWindowResize);
    }

    resizeTimer = null;

    onWindowResizeStop = () => {
      if (!this.mounted) return;

      let oldWidth = this.state.width;
      /* eslint-disable-next-line react/no-find-dom-node */
      const node = ReactDOM.findDOMNode(this);

      this.setState(
        {
          width: node.offsetWidth,
          cols: (node.offsetWidth / oldWidth) * this.state.cols,
        },
        () => {
          this.props.onWidthChange(this.state.width, this.state.cols);
        }
      );
    };

    onWindowResize = () => {
      if (this.resizeTimer) clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(this.onWindowResizeStop, 200);
    };

    render() {
      if (this.props.measureBeforeMount && !this.mounted) {
        return (
          <div className={this.props.className} style={this.props.style} />
        );
      }

      return <ComposedComponent {...this.props} {...this.state} />;
    }
  };

export default Width;
