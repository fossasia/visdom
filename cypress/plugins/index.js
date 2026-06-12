/// <reference types="cypress" />
// ***********************************************************
// This example plugins/index.js can be used to load plugins
//
// You can change the location of this file or turn off loading
// the plugins file with the 'pluginsFile' configuration option.
//
// You can read more here:
// https://on.cypress.io/plugins-guide
// ***********************************************************

// This function is called when a project is opened or re-opened (e.g. due to
// the project's config changing)

/**
 * @type {Cypress.PluginConfig}
 */
// eslint-disable-next-line no-unused-vars
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const pixelmatch = require('pixelmatch').default;
const PNG = require('pngjs').PNG;

function assertSafeToken(name, value) {
  const safePattern = /^[A-Za-z0-9._:-]+$/;
  if (typeof value !== 'string' || value.length === 0 || !safePattern.test(value)) {
    throw new Error(`Invalid value for ${name}: ${value}`);
  }
}


module.exports = (on) => {
  // `on` is used to hook into various events Cypress emits
  // `config` is the resolved Cypress config

  on('task', {
    asyncrun(payload) {
      if (!payload || typeof payload !== 'object') {
        throw new Error('asyncrun requires a payload object.');
      }

      const { run, env, seed, args = [] } = payload;

      assertSafeToken('run', run);
      assertSafeToken('env', env);

      if (!Array.isArray(args)) {
        throw new Error('asyncrun payload field `args` must be an array.');
      }

      args.forEach((arg, index) => {
        assertSafeToken(`args[${index}]`, arg);
      });

      const spawnArgs = [
        'example/demo.py',
        '-testing',
        '-port',
        '8098',
        '-run',
        run,
        '-env',
        env,
      ];

      if (seed !== undefined && seed !== null) {
        const seedValue = Number(seed);
        if (!Number.isFinite(seedValue)) {
          throw new Error(`Invalid value for seed: ${seed}`);
        }
        spawnArgs.push('-seed', String(seedValue));
      }

      if (args.length > 0) {
        spawnArgs.push('-arg', ...args);
      }

      const child = spawn('python', spawnArgs, {
        stdio: 'ignore',
        detached: true,
      });
      child.unref();

      return {
        command: 'python',
        args: spawnArgs,
      };
    },

    numDifferentPixels({
      src1,
      src2,
      diffsrc,
      threshold = 0.0,
      debug = false,
    }) {
      // Read images
      let png1 = PNG.sync.read(fs.readFileSync(src1));
      let png2 = PNG.sync.read(fs.readFileSync(src2));

      // preserve original areas for debug metrics
      const origArea1 = png1.width * png1.height;
      const origArea2 = png2.width * png2.height;

      // If dimensions differ, allow small deltas and crop to overlapping
      // (top-left) region. Throw for large mismatches to avoid masking
      // substantive layout/regression changes.
      const MAX_DIM_DELTA = 4; // pixels; tolerate tiny rounding/layout differences
      const deltaW = Math.abs(png1.width - png2.width);
      const deltaH = Math.abs(png1.height - png2.height);

      let width = png1.width;
      let height = png1.height;
      if (deltaW > 0 || deltaH > 0) {
        if (deltaW > MAX_DIM_DELTA || deltaH > MAX_DIM_DELTA) {
          throw new Error(
            'Images have differing dimensions beyond allowed tolerance for comparison. ' +
              `src1: ${src1} (${png1.width}x${png1.height}), ` +
              `src2: ${src2} (${png2.width}x${png2.height})`
          );
        }

        const minWidth = Math.min(png1.width, png2.width);
        const minHeight = Math.min(png1.height, png2.height);

        const cropped1 = new PNG({ width: minWidth, height: minHeight });
        const cropped2 = new PNG({ width: minWidth, height: minHeight });

        // use pngjs's bitblt helper to copy the top-left region
        PNG.bitblt(png1, cropped1, 0, 0, minWidth, minHeight, 0, 0);
        PNG.bitblt(png2, cropped2, 0, 0, minWidth, minHeight, 0, 0);

        png1 = cropped1;
        png2 = cropped2;
        width = minWidth;
        height = minHeight;
        console.warn(
          `image-compare: cropped to ${width}x${height} (delta ${deltaW}x${deltaH}) for comparison: ${src1} vs ${src2}`
        );
      }

      const diff = new PNG({ width, height });
      const appliedThreshold = debug ? 0 : threshold;

      const numDiffPixels = pixelmatch(
        png1.data,
        png2.data,
        diff.data,
        width,
        height,
        { threshold: appliedThreshold }
      );

      fs.mkdirSync(path.dirname(diffsrc), { recursive: true });
      fs.writeFileSync(diffsrc, PNG.sync.write(diff));

      if (debug) {
        const overlapArea = width * height;
        const maxArea = Math.max(origArea1, origArea2);
        const overlapFraction = numDiffPixels / overlapArea;
        const normalizedFraction = numDiffPixels / maxArea;
        const debugData = {
          numDiffPixels,
          overlapArea,
          maxArea,
          overlapFraction,
          normalizedFraction,
        };
        fs.writeFileSync(`${diffsrc}.num`, String(normalizedFraction));
        fs.writeFileSync(`${diffsrc}.num.json`, JSON.stringify(debugData));
      }

      return numDiffPixels;
    },
  });

  on('after:screenshot', (details) => {
    if (details.specName.endsWith('.init.js')) {
      const newPath = details.path.replace(
        `/${details.specName}`,
        `_init/${details.specName}`
      );

      fs.mkdirSync(path.dirname(newPath), { recursive: true });
      fs.renameSync(details.path, newPath);

      return {
        path: newPath,
      };
    }

    return details;
  });
};

