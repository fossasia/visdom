/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import EventSystem from './EventSystem';
const Pane = require('./Pane');
import * as THREE from 'three';
import * as d3 from 'd3-zoom';
import { select, event as currentEvent, mouse } from 'd3-selection';
import debounce from 'debounce';
import lasso from './lasso';
import { polygonContains } from 'd3-polygon';

class EmbeddingsPane extends React.Component {
  onEvent = e => {
    if (!this.props.isFocused) {
      return;
    }

    switch (e.type) {
      case 'keydown':
      case 'keypress':
        e.preventDefault();
        break;
      case 'keyup':
        this.props.appApi.sendPaneMessage({
          event_type: 'KeyPress',
          key: event.key,
          key_code: event.keyCode,
          pane_data: false, // No need to send the full data for this
        });
        break;
    }
  };

  onEntitySelection = e => {
    // TODO: [FIX] There's a bug when two embeddings view are opened,
    // only the focused one will have its tooltip values updated,
    // even if hovering over the unfocused view
    this.props.appApi.sendPaneMessage({
      event_type: 'EntitySelected',
      entityId: e.name,
      idx: e.idx,
      pane_data: false, // No need to send the full data for this
    });
  };

  onRegionSelection = pointIdxs => {
    this.props.appApi.sendPaneMessage({
      event_type: 'RegionSelected',
      selectedIdxs: pointIdxs,
      pane_data: false, // No need to send the full data for this
    });
  };

  // Used to pop an embeddings drilldown off of the stack
  onGoBack = () => {
    this.props.appApi.sendEmbeddingPop({
      pane_data: false, // No need to send the full data for this
    });
  };

  componentDidMount() {
    EventSystem.subscribe('global.event', this.onEvent);
  }
  UNSAFE_componentWillMount() {
    EventSystem.unsubscribe('global.event', this.onEvent);
  }

  handleDownload = () => {
    var blob = new Blob([this.props.content], { type: 'text/plain' });
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.download = 'visdom_text.txt';
    link.href = url;
    link.click();
  };

  render() {
    return (
      <Pane {...this.props} handleDownload={this.handleDownload}>
        <Scene
          key={this.props.height + '===' + this.props.width}
          content={this.props.content}
          height={this.props.height}
          width={this.props.width}
          onSelect={this.onEntitySelection}
          onRegionSelection={this.onRegionSelection}
          interactive={this.props.isFocused}
        />
      </Pane>
    );
  }
}

class Scene extends React.Component {
  state = { detailsLoading: false };

  constructor(props) {
    super(props);

    this.start = this.start.bind(this);
    this.stop = this.stop.bind(this);
    this.animate = this.animate.bind(this);
  }

  componentWillReceiveProps(nextProps) {
    this.setState({ detailsLoading: false });

    if (nextProps.interactive !== this.props.interactive) {
      if (nextProps.interactive) {
        // set up handlers
        this.setUpMouseInteractions();
      } else {
        // remove handlers
        this.removeMouseInteractions();
      }
    }
  }

  removeMouseInteractions() {
    const { renderer, zoom } = this;
    let view = select(renderer.domElement);

    view.on('mousemove', null);
    view.on('mouseleave', null);
    zoom.on('zoom', null);
  }

  setUpMouseInteractions() {
    /* ----------------------------------------------------------- */
    // hover stuff

    const { renderer, scene, points, camera, circle_sprite, near, far } = this;

    let view = select(renderer.domElement);

    let raycaster = new THREE.Raycaster();
    raycaster.params.Points.threshold = 30;
    let hoverContainer = new THREE.Object3D();
    scene.add(hoverContainer);

    view.on('mousemove', () => {
      if (!this.props.interactive) return;
      let [mouseX, mouseY] = mouse(view.node());
      let mouse_position = [mouseX, mouseY];
      this.checkIntersects(
        mouse_position,
        points,
        hoverContainer,
        circle_sprite
      );
    });

    view.on('mouseleave', () => {
      this.removeHighlights(hoverContainer);
    });

    this.raycaster = raycaster;

    /* ----------------------------------------------------------- */

    let zoom = d3
      .zoom()
      .scaleExtent([this.getScaleFromZ(far), this.getScaleFromZ(near) - 1]);
    zoom.on('zoom', () => {
      if (!this.props.interactive) return;
      let d3_transform = currentEvent.transform;
      this.lastTransform = currentEvent.transform;
      this.zoomHandler(d3_transform);
    });
    this.zoom = zoom;

    let setUpZoom = () => {
      view.call(zoom);
      let initial_transform;

      if (!this.lastTransform) {
        let initial_scale = this.getScaleFromZ(far);
        initial_transform = d3.zoomIdentity
          .translate(this.props.width / 2, this.props.height / 2)
          .scale(initial_scale);

        camera.position.set(0, 0, far);
      } else {
        initial_transform = this.lastTransform;

        this.zoomHandler(this.lastTransform);
      }

      zoom.transform(view, initial_transform);
    };
    setUpZoom();
    this.zoom = zoom;

    /* ----------------------------------------------------------- */
  }

  componentDidMount() {
    // const width = this.mount.clientWidth;
    // const height = this.mount.clientHeight;

    // References:
    // https://blog.fastforwardlabs.com/2017/10/04/using-three-js-for-2d-data-visualization.html
    // https://codepen.io/WebSeed/pen/MEBoRq

    const width = this.props.width;
    const height = this.props.height;
    let radius = 2000;
    let color_array = [
      '#1f78b4',
      '#b2df8a',
      '#33a02c',
      '#fb9a99',
      '#e31a1c',
      '#fdbf6f',
      '#ff7f00',
      '#6a3d9a',
      '#cab2d6',
      '#ffff99',
    ];
    let circle_sprite = new THREE.TextureLoader().load(
      'https://fastforwardlabs.github.io/visualization_assets/circle-sprite.png'
    );

    let fov = 40;
    let near = 10;
    let far = 7000;

    // Set up camera and scene
    let camera = new THREE.PerspectiveCamera(fov, width / height, near, far);
    camera.position.set(0, 0, far);

    let generated_points = this.props.content.data.map(p =>
      Object.assign({}, p, {
        position: [p.position[0] * radius, p.position[1] * radius],
      })
    );

    let pointsGeometry = new THREE.Geometry();

    let colors = [];
    for (let datum of generated_points) {
      // Set vector coordinates from data
      let vertex = new THREE.Vector3(datum.position[0], datum.position[1], 0);
      pointsGeometry.vertices.push(vertex);
      let color = new THREE.Color(color_array[datum.group]);
      colors.push(color);
    }
    pointsGeometry.colors = colors;

    let pointsMaterial = new THREE.PointsMaterial({
      size: 6,
      sizeAttenuation: false,
      vertexColors: THREE.VertexColors,
      map: circle_sprite,
      transparent: true,
    });

    let points = new THREE.Points(pointsGeometry, pointsMaterial);
    let renderer = new THREE.WebGLRenderer();

    let scene = new THREE.Scene();
    scene.add(points);
    scene.background = new THREE.Color(0xefefef);

    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);

    this.scene = scene;
    this.camera = camera;
    this.renderer = renderer;

    this.fov = fov;
    this.near = near;
    this.far = far;

    this.color_array = color_array;
    this.points = points;
    this.circle_sprite = circle_sprite;
    this.generated_points = generated_points;
    this.debouncedFn = debounce(fn => fn(), 300);

    this.setUpMouseInteractions();

    this.mount.appendChild(this.renderer.domElement);
    this.start();
  }

  componentWillUnmount() {
    this.stop();
    let view = select(this.renderer.domElement);
    view.on('mousemove', null);
    view.on('mouseleave', null);
    this.mount.removeChild(this.renderer.domElement);
  }

  /* utility methods */
  zoomHandler = d3_transform => {
    let scale = d3_transform.k;
    let x = -(d3_transform.x - this.props.width / 2) / scale;
    let y = (d3_transform.y - this.props.height / 2) / scale;
    let z = this.getZFromScale(scale);
    this.raycaster.params.Points.threshold = 30 / (scale * 0.5);
    this.camera.position.set(x, y, z);
  };

  getScaleFromZ(camera_z_position) {
    let half_fov = this.fov / 2;
    let half_fov_radians = this.toRadians(half_fov);
    let half_fov_height = Math.tan(half_fov_radians) * camera_z_position;
    let fov_height = half_fov_height * 2;

    // Divide visualization height by height derived from field of view
    let scale = this.props.height / fov_height;
    return scale;
  }

  getZFromScale(scale) {
    let half_fov = this.fov / 2;
    let half_fov_radians = this.toRadians(half_fov);
    let scale_height = this.props.height / scale;
    let camera_z_position = scale_height / (2 * Math.tan(half_fov_radians));
    return camera_z_position;
  }

  toRadians(angle) {
    return angle * (Math.PI / 180);
  }

  /* end utility methods */

  // start hover interaction stuff

  // Hover and tooltip interaction

  mouseToThree(mouseX, mouseY) {
    return new THREE.Vector3(
      (mouseX / this.props.width) * 2 - 1,
      -(mouseY / this.props.height) * 2 + 1,
      1
    );
  }

  checkIntersects(mouse_position, points, hoverContainer, circle_sprite) {
    let mouse_vector = this.mouseToThree(...mouse_position);
    this.raycaster.setFromCamera(mouse_vector, this.camera);
    let intersects = this.raycaster.intersectObject(points);
    if (intersects[0]) {
      let sorted_intersects = this.sortIntersectsByDistanceToRay(intersects);
      let intersect = sorted_intersects[0];
      let index = intersect.index;
      let datum = this.generated_points[index];
      this.highlightPoint(datum, hoverContainer, circle_sprite);
      this.showTooltip(mouse_position, datum);
    } else {
      this.removeHighlights(hoverContainer);
      this.hideTooltip();
    }
  }

  showTooltip(mouse_position, datum) {
    if (!this.state.hovered || this.state.hovered !== datum) {
      this.setState({ detailsLoading: true });
      this.debouncedFn(() => {
        this.props.onSelect(datum);
      });
    }
    this.setState({ hovered: datum });
  }

  hideTooltip() {
    this.setState({ hovered: null });
  }

  sortIntersectsByDistanceToRay(intersects) {
    // return _.sortBy(intersects, 'distanceToRay');
    return [...intersects].sort((a, b) => a.distanceToRay - b.distanceToRay);
  }

  highlightPoint(datum, hoverContainer, circle_sprite) {
    this.removeHighlights(hoverContainer);

    let geometry = new THREE.Geometry();
    geometry.vertices.push(
      new THREE.Vector3(datum.position[0], datum.position[1], 0)
    );
    geometry.colors = [new THREE.Color(this.color_array[datum.group])];

    let material = new THREE.PointsMaterial({
      size: 16,
      sizeAttenuation: false,
      vertexColors: THREE.VertexColors,
      map: circle_sprite,
      transparent: true,
    });

    let point = new THREE.Points(geometry, material);
    hoverContainer.add(point);
  }

  removeHighlights(hoverContainer) {
    hoverContainer.remove(...hoverContainer.children);
  }

  // end hover interaction stuff

  start() {
    if (!this.frameId) {
      this.frameId = requestAnimationFrame(this.animate);
    }
  }

  stop() {
    cancelAnimationFrame(this.frameId);
  }

  animate() {
    this.renderScene();
    this.frameId = window.requestAnimationFrame(this.animate);
  }

  renderScene() {
    this.renderer.render(this.scene, this.camera);
  }

  render() {
    return (
      <div style={{ position: 'relative' }}>
        <span
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            zIndex: 1,
            cursor: 'pointer',
          }}
          onClick={e => {
            e.preventDefault();
            this.setState({ selectMode: !this.state.selectMode });
          }}
        >
          {this.state.selectMode ? 'Selecting...' : 'Select'}
        </span>
        {this.state.hovered && (
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: 0,
              backgroundColor: 'rgba(0,0,0,0.77)',
              padding: 5,
              width: 150,
              color: 'white',
            }}
          >
            <strong>{this.state.hovered.name}</strong>
            <br />
            <strong>Label: {this.state.hovered.label}</strong>
            <br />
            {this.props.content.selected && (
              <div
                style={{ opacity: this.state.detailsLoading ? 0.2 : 1 }}
                dangerouslySetInnerHTML={{
                  __html: this.props.content.selected.html,
                }}
              />
            )}
          </div>
        )}
        {this.state.selectMode && (
          <LassoSelection
            width={this.props.width}
            height={this.props.height}
            points={this.props.content.data}
            camera={this.camera}
            onRegionSelection={this.props.onRegionSelection}
          />
        )}
        <div
          style={{
            opacity: this.props.interactive ? 1 : 0.2,
            width: this.props.width + 'px',
            height: this.props.height + 'px',
          }}
          ref={mount => {
            this.mount = mount;
          }}
        />
      </div>
    );
  }
}

class LassoSelection extends React.Component {
  componentDidMount() {
    var lassoInstance = lasso()
      .on('end', polygon => {
        this.props.camera.updateMatrixWorld();

        const points = this.props.points.map(point => {
          /* TEST */
          var p = new THREE.Vector3(
            point.position[0] * 2000,
            point.position[1] * 2000,
            0
          );
          var vector = p.project(this.props.camera);

          vector.x = ((vector.x + 1) / 2) * this.props.width;
          vector.y = (-(vector.y - 1) / 2) * this.props.height;
          /* END TEST */

          const [x, y] = point.position;
          return {
            ref: point,
            old: point.position,
            test: [vector.x, vector.y],
            coords: [
              x * this.props.width,
              y * this.props.height,
              // ((x + 1) * this.props.width) / 2,
              // ((y + 1) * this.props.height) / 2,
            ],
          };
        });
        // console.log(this.props.height, this.props.width, points, polygon);
        const selected = points.filter(point =>
          polygonContains(polygon, point.test)
        );
        console.log(selected.map(pt => pt.ref.idx));
        this.props.onRegionSelection(selected.map(pt => pt.ref.idx));
      })
      .on('start', null);

    select(this.interactionSvg).call(lassoInstance);
  }
  render() {
    return (
      <svg
        ref={mount => (this.interactionSvg = mount)}
        style={{
          width: this.props.width,
          height: this.props.height,
          position: 'absolute',
          top: 0,
          left: 0,
        }}
      />
    );
  }
}

module.exports = EmbeddingsPane;
