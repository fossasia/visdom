/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 */

import React from 'react';
import * as THREE from 'three';
import Pane from './Pane';

function setAttr(geometry, name, attribute) {
  if (geometry.setAttribute) {
    geometry.setAttribute(name, attribute);
  } else {
    geometry.addAttribute(name, attribute);
  }
}

function base64ToFloat32Array(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Float32Array(bytes.buffer);
}

function base64ToUint8Array(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

class OrbitController {
  constructor(camera, domElement, requestRender) {
    this.camera = camera;
    this.domElement = domElement;
    this.requestRender = requestRender;

    this.target = new THREE.Vector3();
    this.radius = 5;
    this.theta = Math.PI / 4;
    this.phi = Math.PI / 3;
    this.minRadius = 0.01;
    this.maxRadius = Infinity;
    this.rotateSpeed = 0.005;
    this.panSpeed = 0.001;
    this.zoomSpeed = 0.1;
    this.savedState = null;

    this._dragging = false;
    this._lastX = 0;
    this._lastY = 0;
    this._isPan = false;

    this._onMouseDown = this._onMouseDown.bind(this);
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseUp = this._onMouseUp.bind(this);
    this._onWheel = this._onWheel.bind(this);
    this._onDblClick = this._onDblClick.bind(this);
    this._onContextMenu = this._onContextMenu.bind(this);

    domElement.addEventListener('mousedown', this._onMouseDown);
    domElement.addEventListener('mousemove', this._onMouseMove);
    domElement.addEventListener('mouseup', this._onMouseUp);
    domElement.addEventListener('mouseleave', this._onMouseUp);
    domElement.addEventListener('wheel', this._onWheel, { passive: false });
    domElement.addEventListener('dblclick', this._onDblClick);
    domElement.addEventListener('contextmenu', this._onContextMenu);
  }

  saveState() {
    this.savedState = {
      target: this.target.clone(),
      radius: this.radius,
      theta: this.theta,
      phi: this.phi,
    };
  }

  reset() {
    if (!this.savedState) return;
    this.target.copy(this.savedState.target);
    this.radius = this.savedState.radius;
    this.theta = this.savedState.theta;
    this.phi = this.savedState.phi;
    this.updateCamera();
    this.requestRender();
  }

  updateCamera() {
    const sinPhi = Math.sin(this.phi);
    this.camera.position.set(
      this.target.x + this.radius * sinPhi * Math.sin(this.theta),
      this.target.y + this.radius * Math.cos(this.phi),
      this.target.z + this.radius * sinPhi * Math.cos(this.theta),
    );
    this.camera.lookAt(this.target);
  }

  _rotate(dx, dy) {
    this.theta -= dx * this.rotateSpeed;
    this.phi = Math.max(1e-3, Math.min(Math.PI - 1e-3, this.phi - dy * this.rotateSpeed));
    this.updateCamera();
    this.requestRender();
  }

  _zoom(deltaY) {
    this.radius = Math.max(
      this.minRadius,
      Math.min(this.maxRadius, this.radius * Math.exp(deltaY * this.zoomSpeed))
    );
    this.updateCamera();
    this.requestRender();
  }

  _pan(dx, dy) {
    this.camera.updateMatrixWorld(true);
    const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
    const s = this.radius * this.panSpeed;
    this.target.addScaledVector(right, -dx * s);
    this.target.addScaledVector(up, dy * s);
    this.updateCamera();
    this.requestRender();
  }

  _onMouseDown(e) {
    e.stopPropagation();
    this._dragging = true;
    this._isPan = e.button === 2 || e.shiftKey;
    this._lastX = e.clientX;
    this._lastY = e.clientY;
  }

  _onMouseMove(e) {
    if (!this._dragging) return;
    e.stopPropagation();
    const dx = e.clientX - this._lastX;
    const dy = e.clientY - this._lastY;
    this._lastX = e.clientX;
    this._lastY = e.clientY;
    if (this._isPan) {
      this._pan(dx, dy);
    } else {
      this._rotate(dx, dy);
    }
  }

  _onMouseUp(e) {
    e.stopPropagation();
    this._dragging = false;
  }

  _onWheel(e) {
    e.preventDefault();
    this._zoom(e.deltaY > 0 ? 1 : -1);
  }

  _onDblClick(e) {
    e.stopPropagation();
    this.reset();
  }

  _onContextMenu(e) {
    e.preventDefault();
  }

  dispose() {
    this.domElement.removeEventListener('mousedown', this._onMouseDown);
    this.domElement.removeEventListener('mousemove', this._onMouseMove);
    this.domElement.removeEventListener('mouseup', this._onMouseUp);
    this.domElement.removeEventListener('mouseleave', this._onMouseUp);
    this.domElement.removeEventListener('wheel', this._onWheel);
    this.domElement.removeEventListener('dblclick', this._onDblClick);
    this.domElement.removeEventListener('contextmenu', this._onContextMenu);
  }
}

class PointCloudPane extends React.Component {
  constructor(props) {
    super(props);
    this.state = { initError: null };
    this.mount = null;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.points = null;
    this.axes = null;
    this.geometry = null;
    this.material = null;
    this.controller = null;
    this.rafId = null;
  }

  componentDidMount() {
    try {
      this.initScene();
      this.initController();
    } catch (e) {
      console.error('PointCloudPane: WebGL initialization failed.', e);
      this.setState({ initError: e.message || 'WebGL is not supported' });
      return;
    }
    if (this.props.content) {
      try {
        this.buildGeometry(this.props);
      } catch (e) {
        console.error('PointCloudPane: failed to build geometry', e);
      }
    }
    this.requestRender();
  }

  componentDidUpdate(prevProps) {
    if (this.state && this.state.initError) return;

    const contentChanged =
      prevProps.content !== this.props.content ||
      prevProps.contentID !== this.props.contentID;
    const sizeChanged =
      prevProps.width !== this.props.width ||
      prevProps.height !== this.props.height;

    if (contentChanged) {
      this.disposeCloud();
      if (this.props.content) {
        try {
          this.buildGeometry(this.props);
        } catch (e) {
          console.error('PointCloudPane: failed to build geometry', e);
        }
      }
    }
    if (sizeChanged) {
      this.handleResize();
    }

    const prevOpts = prevProps.opts || {};
    const nextOpts = this.props.opts || {};

    if (prevOpts.bgcolor !== nextOpts.bgcolor && this.renderer) {
      this.renderer.setClearColor(nextOpts.bgcolor || '#ffffff');
    }

    // Live-update material properties when opts change without new content.
    if (!contentChanged && this.material) {
      const opacityChanged = prevOpts.opacity !== nextOpts.opacity;
      const markersizeChanged = prevOpts.markersize !== nextOpts.markersize;
      const defaultColorChanged = prevOpts.default_color !== nextOpts.default_color;
      if (opacityChanged) {
        const opacity = nextOpts.opacity != null ? nextOpts.opacity : 1.0;
        this.material.opacity = opacity;
        this.material.transparent = opacity < 1.0;
        this.material.depthWrite = opacity >= 1.0;
        this.material.needsUpdate = true;
      }
      if (markersizeChanged) {
        this.material.size = nextOpts.markersize != null ? nextOpts.markersize : 2.0;
        this.material.needsUpdate = true;
      }
      if (defaultColorChanged && !this.material.vertexColors) {
        const dc = nextOpts.default_color || [40, 40, 40];
        this.material.color.setRGB(dc[0] / 255, dc[1] / 255, dc[2] / 255);
        this.material.needsUpdate = true;
      }
    }

    // show_axes changes require a geometry rebuild (axes are scene objects).
    if (!contentChanged && prevOpts.show_axes !== nextOpts.show_axes && this.props.content) {
      this.disposeCloud();
      try {
        this.buildGeometry(this.props);
      } catch (e) {
        console.error('PointCloudPane: failed to rebuild geometry for show_axes change', e);
      }
    }

    this.requestRender();
  }

  componentWillUnmount() {
    this.disposeAll();
  }

  initScene = () => {
    const { width, height } = this.props;
    const opts = this.props.opts || {};

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(width, height);
    this.renderer.setClearColor(opts.bgcolor || '#ffffff');
    this.mount.appendChild(this.renderer.domElement);

    // Surface a user-visible message when the GPU reclaims the WebGL context
    // (e.g. too many concurrent panes, device sleep/wake, driver reset).
    this._onContextLost = (e) => {
      e.preventDefault();
      this.setState({ initError: 'WebGL context lost — reload the page to restore' });
    };
    this.renderer.domElement.addEventListener('webglcontextlost', this._onContextLost);

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(60, width / height, 0.001, 1000);
    this.camera.position.set(0, 0, 5);
  };

  initController = () => {
    this.controller = new OrbitController(
      this.camera,
      this.renderer.domElement,
      this.requestRender
    );
  };

  handleResize = () => {
    const { width, height } = this.props;
    if (!this.renderer || !this.camera) return;
    this.renderer.setSize(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  };

  requestRender = () => {
    if (this.rafId != null) return;
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      if (this.renderer && this.scene && this.camera) {
        this.renderer.render(this.scene, this.camera);
      }
    });
  };

  resetCamera = () => {
    if (this.controller) {
      this.controller.reset();
    }
  };

  buildGeometry = (props) => {
    const content = props.content;
    const opts = props.opts || {};

    // decode xyz
    const xyzFloat32 = base64ToFloat32Array(content.xyz.data);
    const expectedXYZ = content.xyz.shape[0] * content.xyz.shape[1];
    if (xyzFloat32.length !== expectedXYZ) {
      throw new Error(
        'Invalid pointcloud3d xyz payload: expected ' + expectedXYZ +
        ' values, got ' + xyzFloat32.length
      );
    }

    // decode rgb (optional)
    let rgbUint8 = null;
    if (content.rgb) {
      if (content.rgb.shape[1] !== 3) {
        throw new Error(
          'Invalid pointcloud3d rgb payload: expected 3 channels, got ' +
          content.rgb.shape[1]
        );
      }
      rgbUint8 = base64ToUint8Array(content.rgb.data);
      const expectedRGB = content.rgb.shape[0] * content.rgb.shape[1];
      if (rgbUint8.length !== expectedRGB) {
        throw new Error(
          'Invalid pointcloud3d rgb payload: expected ' + expectedRGB +
          ' values, got ' + rgbUint8.length
        );
      }
    }

    const geometry = new THREE.BufferGeometry();
    setAttr(geometry, 'position', new THREE.BufferAttribute(xyzFloat32, 3));

    const hasRGB = rgbUint8 != null;
    if (hasRGB) {
      const colorF = new Float32Array(rgbUint8.length);
      for (let i = 0; i < rgbUint8.length; i++) colorF[i] = rgbUint8[i] / 255.0;
      setAttr(geometry, 'color', new THREE.BufferAttribute(colorF, 3));
    }

    const opacity = opts.opacity != null ? opts.opacity : 1.0;
    // Default markersize is proportional to the cloud radius so points render
    // at ~1-2 screen pixels regardless of cloud scale.
    const defaultSize = radius * 0.01;
    const size = opts.markersize != null ? opts.markersize : defaultSize;
    // THREE.VertexColors (integer 2) was replaced by boolean true in r125+.
    // Support both APIs transparently.
    const vertexColorsOn =
      typeof THREE.VertexColors !== 'undefined' ? THREE.VertexColors : true;
    const vertexColorsOff =
      typeof THREE.NoColors !== 'undefined' ? THREE.NoColors : false;
    const material = new THREE.PointsMaterial({
      size: size,
      sizeAttenuation: true,
      vertexColors: hasRGB ? vertexColorsOn : vertexColorsOff,
      opacity: opacity,
      transparent: opacity < 1.0,
      depthWrite: opacity >= 1.0,
    });

    if (!hasRGB) {
      const dc = opts.default_color || [40, 40, 40];
      material.color = new THREE.Color(dc[0] / 255, dc[1] / 255, dc[2] / 255);
    }

    this.geometry = geometry;
    this.material = material;
    this.points = new THREE.Points(geometry, material);
    this.scene.add(this.points);

    // compute bounds (prefer precomputed from server)
    let center, radius;
    const b = content.bounds;
    if (
      b &&
      Array.isArray(b.center) && b.center.length === 3 &&
      b.center.every(v => typeof v === 'number' && isFinite(v)) &&
      typeof b.radius === 'number' && isFinite(b.radius)
    ) {
      center = new THREE.Vector3(b.center[0], b.center[1], b.center[2]);
      radius = Math.max(b.radius, 1e-6);
    } else {
      geometry.computeBoundingSphere();
      center = geometry.boundingSphere.center.clone();
      radius = Math.max(geometry.boundingSphere.radius, 1e-6);
    }

    // axes helper
    if (opts.show_axes !== false) {
      this.axes = new THREE.AxesHelper(radius);
      this.axes.position.copy(center);
      this.scene.add(this.axes);
    }

    // fit orbit controller to cloud
    const DIST_FACTOR = 2.5;
    this.controller.target.copy(center);
    this.controller.radius = radius * DIST_FACTOR;
    this.controller.theta = Math.PI / 4;
    this.controller.phi = Math.PI / 3;
    this.controller.minRadius = radius * 0.1;
    this.controller.maxRadius = radius * 20;

    // Set clipping planes based on camera distance so near-plane never
    // exceeds the camera-to-target distance (fixes blank render for tiny clouds).
    const camDist = radius * DIST_FACTOR;
    this.camera.near = Math.max(camDist / 1000, 1e-7);
    this.camera.far = Math.max(camDist * 1000, 1000);
    this.camera.updateProjectionMatrix();

    this.controller.updateCamera();
    this.controller.saveState();
  };

  disposeCloud = () => {
    if (this.scene && this.points) { this.scene.remove(this.points); }
    if (this.geometry) { this.geometry.dispose(); this.geometry = null; }
    if (this.material) { this.material.dispose(); this.material = null; }
    this.points = null;

    if (this.scene && this.axes) { this.scene.remove(this.axes); }
    if (this.axes) {
      if (this.axes.geometry) this.axes.geometry.dispose();
      // AxesHelper.material may be an array in some Three.js versions.
      const mat = this.axes.material;
      if (Array.isArray(mat)) {
        mat.forEach(m => { if (m && m.dispose) m.dispose(); });
      } else if (mat && mat.dispose) {
        mat.dispose();
      }
      this.axes = null;
    }
  };

  disposeAll = () => {
    if (this.rafId != null) { cancelAnimationFrame(this.rafId); this.rafId = null; }
    if (this.controller) { this.controller.dispose(); this.controller = null; }

    this.disposeCloud();

    if (this.renderer && this.renderer.domElement) {
      if (this._onContextLost) {
        this.renderer.domElement.removeEventListener('webglcontextlost', this._onContextLost);
        this._onContextLost = null;
      }
      if (this.renderer.domElement.parentNode === this.mount) {
        this.mount.removeChild(this.renderer.domElement);
      }
    }
    if (this.renderer) { this.renderer.dispose(); this.renderer = null; }

    this.scene = this.camera = null;
  };

  render() {
    if (this.state && this.state.initError) {
      return (
        <Pane {...this.props} enablePropertyList={false}>
          <div
            style={{
              width: this.props.width,
              height: this.props.height,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#c00',
              fontFamily: 'monospace',
              fontSize: 14,
              padding: 8,
              boxSizing: 'border-box',
            }}
          >
            {'WebGL unavailable: ' + this.state.initError}
          </div>
        </Pane>
      );
    }
    return (
      <Pane
        {...this.props}
        enablePropertyList={false}
        handleReset={this.resetCamera}
      >
        <div
          ref={el => { this.mount = el; }}
          style={{ width: this.props.width, height: this.props.height }}
        />
      </Pane>
    );
  }
}

export default PointCloudPane;
