# Design: `pointcloud3d` Pane — fossasia/visdom#686

## Summary

Add a first-class `vis.pointcloud3d(xyz, rgb=None, win=None, env=None, opts=None)` method to Visdom that renders a 3D point cloud in a dedicated WebGL pane backed by Three.js. This is a strict MVP (Approach A): inline base64 transport only, no new server routes, no Three.js upgrade, no progressive streaming.

**Issue:** https://github.com/fossasia/visdom/issues/686

---

## Final decisions

| Area | Decision |
|---|---|
| Transport | Inline base64 within existing JSON `_send(..., endpoint="events")` |
| Python API | Direct method on `Visdom` class with `@pytorch_wrap` |
| Camera controls | Custom lightweight orbit controller (no Three.js upgrade) |
| Rendering | `THREE.BufferGeometry` + `THREE.Points` + `THREE.PointsMaterial` |
| MVP scale target | 50k–200k points comfortably; `>200k` warns |
| Payload evolution | Versioned `{version, transport}` envelope from day one |

---

## Section 1 — Architecture

### End-to-end flow

```
vis.pointcloud3d(xyz, rgb, opts)
  → validate + normalize (xyz → float32, rgb → uint8)
  → optional Python-side downsample (when opts.max_points set)
  → base64 encode typed arrays
  → _send({data:[{type:"pointcloud3d", content:{...}}], win, eid, opts},
           endpoint="events")
  → existing Visdom JSON event path (no new server routes)
  → js/settings.js PANES["pointcloud3d"] lookup
  → PointCloudPane.js
  → decode base64 → Float32Array / Uint8Array → Float32Array colors
  → THREE.BufferGeometry + THREE.Points + PointsMaterial
  → custom orbit controller (left-drag rotate, scroll zoom, shift-drag pan, dblclick reset)
  → dirty render loop (requestRender only on data/camera/resize/reset)
```

### Files changed

| File | Action |
|---|---|
| `py/visdom/__init__.py` | Add `pointcloud3d` method + validation + base64 helpers |
| `js/panes/PointCloudPane.js` | New React class component |
| `js/settings.js` | Register pane type + default size |
| `example/components/plot_pointcloud.py` | 2 demo functions |
| `example/demo.py` | Import + call demos |
| `test/test_pointcloud3d.py` | Python unit tests |
| `cypress/integration/pointcloud3d.js` | Smoke + interaction test |

README update is required in the course repository to document the chosen issue and design rationale. An upstream Visdom README update is optional for PR 1 and can be added if maintainers request user-facing documentation.

---

## Section 2 — Python API

### Signature

```python
@pytorch_wrap
def pointcloud3d(self, xyz, rgb=None, win=None, env=None, opts=None):
    """
    Visualize a 3D point cloud using a dedicated WebGL pane.

    Args:
        xyz: Array-like of shape (N, 3). XYZ point coordinates.
        rgb: Optional array-like of shape (N, 3). Per-point RGB colors.
             Supports integer [0, 255], float [0, 1], or float [0, 255].
        win: Optional Visdom window id.
        env: Optional Visdom environment.
        opts: Optional visualization options (see below).

    Returns:
        Visdom window id (str).
    """
```

### `opts` keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `title` | str | None | Window title |
| `markersize` | float | 2.0 | Base point size; visually attenuated by camera depth (`sizeAttenuation: true`) |
| `opacity` | float | 1.0 | Global point opacity |
| `bgcolor` | CSS str | `"#ffffff"` | Scene background color |
| `show_axes` | bool | True | Render axes helper |
| `default_color` | `[R,G,B]` int | `[40, 40, 40]` | Used when `rgb` is None |
| `max_points` | int or None | None | Downsample cap (Python-side, before encode) |
| `downsample` | str or None | None | `"stride"` or `"random"` (only when max_points set) |
| `seed` | int or None | None | RNG seed for `"random"` downsample |
| `camera` | dict or None | None | Optional initial `{target, radius, theta, phi}` |

### Validation rules

| Rule | Exception |
|---|---|
| `xyz` non-coercible | `TypeError("xyz must be array-like and numeric")` |
| `xyz.ndim != 2 or xyz.shape[1] != 3` | `ValueError(f"xyz must have shape (N, 3); got {xyz.shape}")` |
| `xyz.shape[0] == 0` | `ValueError("xyz must contain at least one point")` |
| `not np.isfinite(xyz).all()` | `ValueError("xyz must contain only finite values")` |
| `rgb` non-coercible or non-numeric | `TypeError("rgb must be array-like and numeric")` |
| `rgb.ndim != 2 or rgb.shape != xyz.shape` | `ValueError(f"rgb must have shape ({N}, 3); got {rgb.shape}")` |
| `not np.isfinite(rgb).all()` | `ValueError("rgb must contain only finite values")` |
| integer rgb outside `[0, 255]` | `ValueError("integer rgb values must be in [0, 255]")` |
| any float rgb < 0, or max > 255.0 | `ValueError("float rgb values must be in [0, 1] or [0, 255]")` |
| `max_points` set with `downsample="none"` | `ValueError("max_points and downsample='none' conflict")` |
| `max_points <= 0` | `ValueError("opts['max_points'] must be a positive integer")` |
| `downsample` not in `{None, "stride", "random"}` (includes string `"none"`) | `ValueError("opts['downsample'] must be 'stride' or 'random'")` |
| `opacity` outside `[0, 1]` | `ValueError("opts['opacity'] must be between 0 and 1")` |
| `markersize <= 0` | `ValueError("opts['markersize'] must be > 0")` |

### Normalization

**xyz:** `np.ascontiguousarray(xyz.astype("<f4", copy=False))` — explicit little-endian float32.

**rgb:**
Detection order (checked before casting):
1. Any value < 0 → raise `ValueError`
2. Any value > 255.0 → raise `ValueError`
3. integer dtype: values must be in `[0, 255]`; cast to uint8
4. float dtype, max ≤ 1.0: scale by 255, round, clip `[0, 255]`, cast to uint8
5. float dtype, 1.0 < max ≤ 255.0: round, clip `[0, 255]`, cast to uint8

Float array with max of 1.5 falls into case 5 (treated as `[0, 255]` range).
Final: `np.ascontiguousarray(rgb)`

### Downsampling policy

```
if max_points is None:
    if N > 200_000:
        warnings.warn("pointcloud3d is using inline base64 transport. "
                      "Point clouds above 200,000 points may be slow. "
                      "Use opts['max_points'] to downsample explicitly.", UserWarning)
    send full cloud

elif N <= max_points:
    send full cloud

else:
    mode = downsample or "stride"
    if mode == "stride":
        idx = np.round(np.linspace(0, N-1, max_points)).astype(int)
    elif mode == "random":
        rng = np.random.default_rng(seed)
        idx = rng.choice(N, max_points, replace=False)
    xyz = xyz[idx]
    if rgb is not None:
        rgb = rgb[idx]
```

### `_send` call

```python
return self._send(
    {
        "data": [
            {
                "type": "pointcloud3d",
                "content": content,
            }
        ],
        "win": win,
        "eid": env,
        "opts": opts,
    },
    endpoint="events",
)
```

### Payload `content` schema

```json
{
  "version": 1,
  "transport": "inline_base64",
  "xyz": {
    "dtype": "float32",
    "shape": [100000, 3],
    "encoding": "base64",
    "byte_order": "little",
    "order": "C",
    "data": "..."
  },
  "rgb": {
    "dtype": "uint8",
    "shape": [100000, 3],
    "encoding": "base64",
    "order": "C",
    "data": "..."
  },
  "num_points_original": 100000,
  "num_points_rendered": 100000,
  "bounds": {
    "min": [-1.0, -1.0, -1.0],
    "max": [1.0, 1.0, 1.0],
    "center": [0.0, 0.0, 0.0],
    "radius": 1.732
  }
}
```

`rgb` is omitted (not null) when no RGB data is provided. `bounds` is computed Python-side from the downsampled xyz to avoid recomputing in JS.

### Usage examples

```python
import numpy as np
from visdom import Visdom

viz = Visdom()
xyz = np.random.randn(100_000, 3).astype(np.float32)

# XYZ only
viz.pointcloud3d(xyz, opts={"title": "XYZ cloud", "markersize": 2, "show_axes": True})

# XYZRGB with downsampling
rgb = np.random.randint(0, 256, size=(100_000, 3), dtype=np.uint8)
viz.pointcloud3d(
    xyz, rgb=rgb,
    opts={"title": "RGB cloud", "max_points": 50_000, "downsample": "stride"},
)
```

---

## Section 3 — Frontend Pane

### Component

`PointCloudPane` is a class component. It owns imperative Three.js resources (scene, camera, renderer, geometry, material, points, orbit controller, RAF id) that require explicit lifecycle management. This matches the style of `EmbeddingsPane.js`.

### Mount / update / unmount

```
componentDidMount:
  initScene()           → WebGLRenderer, PerspectiveCamera, Scene
  initController()      → attach DOM events, create initial orbit state
  buildGeometry(props)  → decode, BufferGeometry, Points, fit camera, save reset state
  requestRender()

componentDidUpdate(prevProps):
  contentChanged = prevProps.content !== this.props.content
                || prevProps.contentID !== this.props.contentID
  sizeChanged    = prevProps.width  !== this.props.width
                || prevProps.height !== this.props.height

  if contentChanged: dispose old cloud, rebuildGeometry(props)
  if sizeChanged:    resize renderer, update camera aspect + projection
  requestRender()

componentWillUnmount:
  disposeAll()
```

The controller is initialized before geometry fitting because the fit step writes the initial `target`, `radius`, `theta`, and `phi` into the controller. After camera fitting, the controller saves this state as `savedState` so double-click reset and toolbar reset return to the initial fitted view.

### Geometry

```js
function setAttr(geometry, name, attribute) {
  // compatibility shim for three@0.105.x (addAttribute) vs newer (setAttribute)
  if (geometry.setAttribute) {
    geometry.setAttribute(name, attribute);
  } else {
    geometry.addAttribute(name, attribute);
  }
}

// validate decoded lengths match declared shape before building geometry
const expectedXYZ = content.xyz.shape[0] * content.xyz.shape[1];
if (xyzFloat32.length !== expectedXYZ) {
  throw new Error(
    `Invalid pointcloud3d xyz payload: expected ${expectedXYZ} values, got ${xyzFloat32.length}`
  );
}
if (rgbUint8) {
  const expectedRGB = content.rgb.shape[0] * content.rgb.shape[1];
  if (rgbUint8.length !== expectedRGB) {
    throw new Error(
      `Invalid pointcloud3d rgb payload: expected ${expectedRGB} values, got ${rgbUint8.length}`
    );
  }
}

// position: Float32Array, itemSize=3
setAttr(geometry, 'position', new THREE.BufferAttribute(xyzFloat32, 3));

// color: convert uint8 → Float32Array, itemSize=3
// (avoids relying on normalized Uint8Array behavior in pinned three@0.105.x)
if (rgbUint8) {
  const colorF = new Float32Array(rgbUint8.length);
  for (let i = 0; i < rgbUint8.length; i++) colorF[i] = rgbUint8[i] / 255.0;
  setAttr(geometry, 'color', new THREE.BufferAttribute(colorF, 3));
}
```

### Material

```js
const material = new THREE.PointsMaterial({
  size: opts.markersize ?? 2.0,
  sizeAttenuation: true,
  vertexColors: hasRGB ? THREE.VertexColors : THREE.NoColors,
  opacity: opts.opacity ?? 1.0,
  transparent: (opts.opacity ?? 1.0) < 1.0,
  depthWrite: (opts.opacity ?? 1.0) >= 1.0,  // reduces artifacts for translucent clouds
});

if (!hasRGB) {
  const [r, g, b] = opts.default_color ?? [40, 40, 40];
  material.color = new THREE.Color(r / 255, g / 255, b / 255);
}
```

### Camera fit

Prefer `content.bounds` (computed Python-side); fall back to `geometry.computeBoundingSphere()`:

```js
let center, radius;
if (content.bounds) {
  center = new THREE.Vector3(...content.bounds.center);
  radius = Math.max(content.bounds.radius, 1e-6);
} else {
  geometry.computeBoundingSphere();
  center = geometry.boundingSphere.center.clone();
  radius = Math.max(geometry.boundingSphere.radius, 1e-6);
}

// Update camera clipping to handle very large or very small clouds
camera.near = Math.max(radius / 1000, 0.001);
camera.far  = Math.max(radius * 1000, 1000);
camera.updateProjectionMatrix();

// Position camera at spherical offset from center
const DIST_FACTOR = 2.5;
this.controller.target.copy(center);
this.controller.radius = radius * DIST_FACTOR;
this.controller.theta  = Math.PI / 4;
this.controller.phi    = Math.PI / 3;
this.controller.updateCamera();
```

### Dirty render loop

```js
requestRender = () => {
  if (this.rafId != null) return;
  this.rafId = requestAnimationFrame(() => {
    this.rafId = null;
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  });
};
```

Triggered only on: data load, camera move, pane resize, reset.

The inner null check (`if (this.renderer && this.scene && this.camera)`) guards against any stale RAF callback that fires after `disposeAll` begins — `this.renderer` is set to null in teardown before `this.scene`/`this.camera`, so the callback exits cleanly without an additional mutex.

### Orbit controller state

| Field | Type | Meaning |
|---|---|---|
| `target` | `THREE.Vector3` | Orbit focus point |
| `radius` | number | Camera distance from target |
| `theta` | number | Azimuth angle (radians) |
| `phi` | number | Polar angle (radians) |
| `minRadius` / `maxRadius` | number | Zoom bounds |
| `rotateSpeed` | number | Radians per pixel |
| `panSpeed` | number | Target translation scale |
| `zoomSpeed` | number | Exponential dolly scale |
| `savedState` | object | Reset snapshot |

### Orbit controller event mapping

| Input | Action |
|---|---|
| Left drag | Rotate: update theta and phi |
| Scroll wheel / trackpad | Dolly: scale radius |
| Right drag | Pan target in camera plane |
| Shift + left drag | Pan fallback for trackpads |
| Double click | Reset to savedState |
| Toolbar reset button | Reset to savedState |

Wheel listener uses `{ passive: false }` and calls `event.preventDefault()`. Drag events call `event.stopPropagation()`.

### `updateCamera` core

```js
updateCamera() {
  const sinPhi = Math.sin(this.phi);
  this.camera.position.set(
    this.target.x + this.radius * sinPhi * Math.sin(this.theta),
    this.target.y + this.radius * Math.cos(this.phi),
    this.target.z + this.radius * sinPhi * Math.cos(this.theta),
  );
  this.camera.lookAt(this.target);
}

rotate(dx, dy) {
  this.theta -= dx * this.rotateSpeed;
  this.phi = Math.max(1e-3, Math.min(Math.PI - 1e-3, this.phi - dy * this.rotateSpeed));
  this.updateCamera();
  this.requestRender();
}

zoom(deltaY) {
  this.radius = Math.max(this.minRadius,
    Math.min(this.maxRadius, this.radius * Math.exp(deltaY * this.zoomSpeed)));
  this.updateCamera();
  this.requestRender();
}

pan(dx, dy) {
  this.camera.updateMatrixWorld(true);
  const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
  const up    = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
  const s     = this.radius * this.panSpeed;
  this.target.addScaledVector(right, -dx * s);
  this.target.addScaledVector(up,     dy * s);
  this.updateCamera();
  this.requestRender();
}
```

### Teardown sequence

```js
disposeAll = () => {
  if (this.rafId != null) { cancelAnimationFrame(this.rafId); this.rafId = null; }

  if (this.controller) { this.controller.dispose(); this.controller = null; }

  if (this.scene && this.points) this.scene.remove(this.points);

  if (this.geometry) { this.geometry.dispose(); this.geometry = null; }
  if (this.material) { this.material.dispose(); this.material = null; }

  if (this.scene && this.axes) { this.scene.remove(this.axes); }
  if (this.axes) {
    if (this.axes.geometry) this.axes.geometry.dispose();
    if (this.axes.material) this.axes.material.dispose();
    this.axes = null;
  }

  if (
    this.renderer &&
    this.renderer.domElement &&
    this.renderer.domElement.parentNode === this.mount
  ) {
    this.mount.removeChild(this.renderer.domElement);
  }
  if (this.renderer) { this.renderer.dispose(); this.renderer = null; }

  this.points = this.scene = this.camera = null;
};
```

### Pane shell

```jsx
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
```

Property list disabled — exposing large base64 strings would be slow and unhelpful.

### `js/settings.js` changes

```js
import PointCloudPane from './panes/PointCloudPane';

const PANES = {
  // ... existing entries ...
  pointcloud3d: PointCloudPane,
};

const PANE_SIZE = {
  // ... existing entries ...
  pointcloud3d: [30, 24],
};
```

---

## Section 4 — Testing

### Python unit tests (`test/test_pointcloud3d.py`)

- Shape validation: wrong ndim, wrong ncols, empty cloud
- Non-finite rejection: NaN, +Inf in xyz and rgb
- RGB normalization: int `[0,255]`, float `[0,1]`, float `[0,255]`, out-of-range rejection
- Downsampling: stride produces correct count, random reproducible with seed
- Payload structure: `version=1`, `transport="inline_base64"`, xyz/rgb dtype/shape, bounds fields, `num_points_original`, `num_points_rendered`
- `max_points` + `downsample="none"` conflict raises `ValueError`
- Large cloud warning: `N > 200_000` without `max_points` emits `UserWarning`
- PyTorch tensor input (via `@pytorch_wrap`)

### Cypress smoke test (`cypress/integration/pointcloud3d.js`)

1. `cy.visit('/')`
2. `cy.run('plot_pointcloud_basic')`
3. Assert pane with expected title exists
4. Assert `canvas` element exists inside pane content
5. Spy on `console.error`; assert no frontend crash
6. Simulate left-drag on canvas
7. Simulate wheel event
8. Click reset button
9. Assert canvas still mounted, pane still present

Use smoke/interactivity assertions, not pixel-perfect render diffs (3D rasterization is noisy).

### Demo components (`example/components/plot_pointcloud.py`)

```python
def plot_pointcloud_basic(viz, env, args):
    n = int(args[0]) if args else 100_000
    xyz = np.random.randn(n, 3).astype(np.float32)
    return viz.pointcloud3d(
        xyz, env=env,
        opts=dict(title=f"Point cloud ({n} pts)", markersize=2, show_axes=True),
    )

def plot_pointcloud_rgb(viz, env, args):
    n = int(args[0]) if args else 100_000
    xyz = np.random.randn(n, 3).astype(np.float32)
    rgb = np.random.randint(0, 256, size=(n, 3), dtype=np.uint8)
    return viz.pointcloud3d(
        xyz, rgb=rgb, env=env,
        opts=dict(title=f"RGB cloud ({n} pts)", markersize=2,
                  max_points=50_000, downsample="stride"),
    )
```

---

## Section 5 — Payload versioning and future work

`version` and `transport` are independent fields. This keeps the public API stable as transports evolve:

| Phase | Transport | Change |
|---|---|---|
| PR 1 (this PR) | `"inline_base64"` | No server changes |
| Phase 2 | `"binary_url"` | New server blob endpoint; pane fetches ArrayBuffer |
| Phase 3 | `"chunks"` | Progressive descriptors; incremental geometry updates |

When Visdom eventually upgrades beyond `three:^0.105.2`:
- Custom orbit controller can be replaced by `OrbitControls` from `three/examples/jsm/controls/OrbitControls.js`
- `THREE.VertexColors` (int 2) and `THREE.NoColors` (int 0) were removed as named exports in three@0.130+; replace with `2` and `0` literals or import from `three/src/constants`
- `geometry.addAttribute` → `geometry.setAttribute` (shim already handles this)

The public method signature `vis.pointcloud3d(xyz, rgb=None, win=None, env=None, opts=None)` stays stable across all phases.

---

## Time estimate

| Item | Hours |
|---|---|
| Python API, validation, base64 helpers | 6–8 |
| Payload shaping + `_send` wiring | 3–4 |
| `PointCloudPane.js` renderer + geometry | 8–10 |
| Custom orbit controller | 6–8 |
| Resize, reset, teardown | 3–4 |
| Example/demo wiring | 2–3 |
| Python + Cypress tests | 5–7 |
| README/docs (if requested) | 2–3 |
| **Total** | **35–47 hrs** |

---

## PR checklist

- [ ] Add `@pytorch_wrap` + `pointcloud3d` to `py/visdom/__init__.py`
- [ ] Add validation, normalization, base64 helpers, bounds computation
- [ ] Add `js/panes/PointCloudPane.js`
- [ ] Register in `js/settings.js` (PANES + PANE_SIZE)
- [ ] Disable property list; wire reset to orbit controller
- [ ] Add `example/components/plot_pointcloud.py` (2 demo functions)
- [ ] Import demos into `example/demo.py`
- [ ] Add `test/test_pointcloud3d.py`
- [ ] Add `cypress/integration/pointcloud3d.js`
- [ ] Run `npm run build` → commit updated `static/js/main.js` + `main.js.map` as a separate "build" commit (matches repo pattern: see commit `54e5a80`)
- [ ] Update course README with issue link, problem summary, and design rationale
- [ ] (Optional for upstream PR) Update Visdom README/docs if maintainers request user-facing documentation
