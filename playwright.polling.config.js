/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { defineConfig } = require('@playwright/test');
const baseConfig = require('./playwright.config');

module.exports = defineConfig({
  ...baseConfig,
  metadata: {
    ...baseConfig.metadata,
    transport: 'polling',
  },
  outputDir: './playwright/test-results-polling',
  reporter: [
    ['html', { outputFolder: 'playwright/playwright-report-polling' }],
  ],
  testIgnore: ['**/*.init.spec.js', '**/screenshots.spec.js'],
  webServer: {
    ...baseConfig.webServer,
    command:
      'visdom -port 8098 -env_path playwright/tmp/polling ' +
      '-use_frontend_client_polling',
    reuseExistingServer: false,
  },
  projects: baseConfig.projects.map((project) => ({
    ...project,
    name: `${project.name}-polling`,
  })),
});
