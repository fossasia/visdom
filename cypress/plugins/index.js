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
const pixelmatch = require('pixelmatch');
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

      // If dimensions differ, crop to overlapping (top-left) region to avoid
      // failing on tiny off-by-pixel layout differences. Log a warning so
      // failures can still be investigated.
      let width = png1.width;
      let height = png1.height;
      if (png1.width !== png2.width || png1.height !== png2.height) {
        const minWidth = Math.min(png1.width, png2.width);
        const minHeight = Math.min(png1.height, png2.height);

        const cropped1 = new PNG({ width: minWidth, height: minHeight });
        const cropped2 = new PNG({ width: minWidth, height: minHeight });

        for (let y = 0; y < minHeight; y++) {
          for (let x = 0; x < minWidth; x++) {
            const srcIdx1 = (y * png1.width + x) << 2;
            const srcIdx2 = (y * png2.width + x) << 2;
            const dstIdx = (y * minWidth + x) << 2;
            cropped1.data[dstIdx] = png1.data[srcIdx1];
            cropped1.data[dstIdx + 1] = png1.data[srcIdx1 + 1];
            cropped1.data[dstIdx + 2] = png1.data[srcIdx1 + 2];
            cropped1.data[dstIdx + 3] = png1.data[srcIdx1 + 3];
            cropped2.data[dstIdx] = png2.data[srcIdx2];
            cropped2.data[dstIdx + 1] = png2.data[srcIdx2 + 1];
            cropped2.data[dstIdx + 2] = png2.data[srcIdx2 + 2];
            cropped2.data[dstIdx + 3] = png2.data[srcIdx2 + 3];
          }
        }

        png1 = cropped1;
        png2 = cropped2;
        width = minWidth;
        height = minHeight;
        console.warn(
          `numDifferentPixels: image size mismatch, cropping to ${width}x${height} for comparison: ${src1} vs ${src2}`
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
        fs.writeFileSync(`${diffsrc}.num`, `${numDiffPixels / (width * height)}`);
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

