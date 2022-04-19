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
}
