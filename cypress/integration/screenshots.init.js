beforeEach(() => {
  cy.visit('/');
});

import {
  all_screenshots,
  all_compareviews,
} from '../support/screenshots.config.js';

describe(`Take plot screenshots`, () => {
  all_screenshots.forEach((run) => {
    it(`Screenshot for ${run}`, () => {
      cy.run(run);

      // ImagePane requires an additional rerender for the image to adjust to the Pane size correctly
      if (run.startsWith('image_')) cy.wait(600);
      // LaTeX plots use MathJax which renders asynchronously - wait for typesetting to finish
      if (run.startsWith('misc_plot_latex')) cy.waitForMathJax();
      cy.waitForPlotRender();
      cy.get('.content').screenshot(run, { overwrite: true });
    });
  });
});

describe(`Take compare-view screenshots`, () => {
  all_compareviews.forEach((run) => {
    it(`Screenshot for ${run}`, () => {
      var num_runs = 3;

      var envs = [];
      for (var i = 0; i < num_runs; i++) {
        // Append a suffix to ensure the environment name is > 25 characters
        var env = run + '_' + i + '_long_env_name_for_testing';
        cy.run(run, {
          env: env,
          open: false,
          seed: 42 + i,
          args: [run],
          asyncrun: false,
        });
        envs.push(env);
      }
      cy.close_envs();
      for (var i = 0; i < num_runs; i++) {
        cy.open_env(envs[i]);
      }
      cy.waitForPlotRender();
      cy.get('.content')
        .first()
        .screenshot('compare_' + run, { overwrite: true });
    });
  });
});

describe(`Take screenshot for PlotPane functions`, () => {
  it('Screenshot for Property Change (using Line Plot)', () => {
    cy.run('plot_line_basic');
    cy.get('.layout .window').should('have.length', 1);
    cy.get('button[title="properties"]', { timeout: 15000 })
      .should('be.visible')
      .click();

    // change some settings
    const change = (key, val) =>
      cy
        .get('td.table-properties-name')
        .contains(key)
        .siblings('td.table-properties-value')
        .find('input')
        .clear()
        .type(val);

    // plot settings
    change('name', 'a line');
    change('type', 'bar');
    change('opacity', '0.75');
    change('marker.line.width', '5');
    change('marker.line.color', '#0FF');

    // layout settings
    change('margin.l', '10');
    change('margin.r', '10');
    change('margin.b', '10');
    change('margin.t', '10');
    change('xaxis.type', 'log');

    // apply settings
    cy.get('button[title="properties"]', { timeout: 15000 })
      .should('be.visible')
      .click();

    cy.waitForPlotRender();
    const run = 'change-properties';
    cy.get('.content').first().screenshot(run, { overwrite: true });
  });
});
