/// <reference types="cypress" />

// ***********************************************************
// Custom Plugin Configuration
//
// This plugins file extends Cypress with custom Node-side
// functionality that cannot run in the browser.
//
// It provides:
//
// • Custom tasks via `on('task')`
//   - `asyncrun`: runs a detached background process
//   - `numDifferentPixels`: compares two PNG images and
//     returns the number of differing pixels using pixelmatch
//
// • Screenshot post-processing via `after:screenshot`
//   - Automatically moves screenshots of `.init.js` specs
//     into a dedicated `_init/` folder.
//
// These tasks allow advanced filesystem access,
// image comparison, and system-level operations during tests.
// ***********************************************************

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const pixelmatch = require('pixelmatch');
const PNG = require('pngjs').PNG;

/**
 * @type {Cypress.PluginConfig}
 */
module.exports = (on, config) => {

  // -----------------------------
  // Tasks
  // -----------------------------
  on('task', {

    // Run async detached command
    asyncrun(cmd) {
      if (typeof cmd !== 'string') {
        throw new Error('Command must be a string');
      }

      const parts = cmd.trim().split(/\s+/);
      const command = parts[0];
      if (!command) {
        throw new Error('Command must be a non-empty string');
      }

      // Security: Whitelist allowed executables to prevent command injection
      // Normalize to basename so absolute/relative paths like `/usr/bin/python3`
      // or `C:\Python39\python.exe` are still validated correctly.
      const executable = path.basename(command);
      const allowedCommands = ['python', 'python3', 'python.exe'];
      if (!allowedCommands.includes(executable)) {
        throw new Error(`Execution of '${command}' is not permitted for security reasons.`);
      }

      const args = parts.slice(1);

      const child = spawn(command, args, {
        stdio: 'ignore', // piping all stdio to /dev/null
        detached: true,
        shell: false
      });

      child.unref();

      // Cypress tasks must return a value; returning null for fire-and-forget
      return null;
    },


    // Compare two PNG images and count different pixels
    numDifferentPixels({ src1, src2, diffsrc, threshold = 0.0, debug = false }) {

      if (!fs.existsSync(src1)) {
        throw new Error(`Source image not found: ${src1}`);
      }

      if (!fs.existsSync(src2)) {
        throw new Error(`Source image not found: ${src2}`);
      }

      let img1;
      try {
        const img1Buffer = fs.readFileSync(src1);
        img1 = PNG.sync.read(img1Buffer);
      } catch (err) {
        throw new Error(`Failed to read or parse source image (${src1}): ${err.message}`);
      }

      let img2;
      try {
        const img2Buffer = fs.readFileSync(src2);
        img2 = PNG.sync.read(img2Buffer);
      } catch (err) {
        throw new Error(`Failed to read or parse source image (${src2}): ${err.message}`);
      }

      // Validate dimensions
      if (img1.width !== img2.width || img1.height !== img2.height) {
        throw new Error('Images must have the same dimensions');
      }

      const { width, height } = img1;
      const diff = new PNG({ width, height });

      const actualThreshold = debug ? 0 : threshold;

      const numDiffPixels = pixelmatch(
        img1.data,
        img2.data,
        diff.data,
        width,
        height,
        { threshold: actualThreshold }
      );

      // Ensure output directory exists
      fs.mkdirSync(path.dirname(diffsrc), { recursive: true });

      // Write diff image
      fs.writeFileSync(diffsrc, PNG.sync.write(diff));

      // Optional debug output
      if (debug) {
        const ratio = numDiffPixels / (width * height);
        fs.writeFileSync(`${diffsrc}.num`, String(ratio));
      }

      return numDiffPixels;
    }

  });


  // -----------------------------
  // After Screenshot Hook
  // -----------------------------
  on('after:screenshot', (details) => {

    if (details.specName && details.specName.endsWith('.init.js')) {

      // Cross-platform path construction
      const screenshotName = path.basename(details.path);
      const specFolder = path.dirname(details.path);
      const screenshotsDir = path.dirname(specFolder);

      const newPath = path.join(
        screenshotsDir,
        '_init',
        details.specName,
        screenshotName
      );

      // Ensure directory exists
      fs.mkdirSync(path.dirname(newPath), { recursive: true });

      // Move screenshot
      fs.renameSync(details.path, newPath);

      // Important: return updated path to Cypress
      return {
        path: newPath
      };
    }

    // If nothing changed, return original details
    return details;
  });

};
