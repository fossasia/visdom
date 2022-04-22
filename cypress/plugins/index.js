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


module.exports = (on, config) => {
  // `on` is used to hook into various events Cypress emits
  // `config` is the resolved Cypress config

  on('task', {
    asyncrun(cmd) {
        cmd = cmd.split(" ")
        const args = cmd.splice(1)
        a = spawn(cmd[0], args, {
            stdio: 'ignore', // piping all stdio to /dev/null
            detached: true
        }).unref();
      return [cmd, args]
    },
  })

  on('task', {
    numDifferentPixels({src1, src2, diffsrc, threshold=0.0, debug=false}) {
        const img1 = PNG.sync.read(fs.readFileSync(src1));
        const img2 = PNG.sync.read(fs.readFileSync(src2));
        const {width, height} = img1;
        const diff = new PNG({width, height});
        if (debug)
            threshold = 0
        num_diff_pixels = pixelmatch(img1.data, img2.data, diff.data, width, height, {threshold: threshold});
        fs.mkdirSync(path.dirname(diffsrc), {recursive: true}, (err) => { if(err) throw err;})
        fs.writeFileSync(diffsrc, PNG.sync.write(diff));
        if (debug)
            fs.writeFileSync(diffsrc+".num", (num_diff_pixels / (width * height)) + "");
      return num_diff_pixels
    },
  })

  on('after:screenshot', (details) => {
    if ((details.specName).endsWith(".init.js")) {
        newpath = details.path.replace("/"+details.specName, "_init/"+details.specName)
        fs.mkdirSync(path.dirname(newpath), {recursive: true}, (err) => { })
        fs.renameSync(details.path, newpath, (err) => { if(err) throw err; })
    }
  })
}

