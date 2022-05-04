before(() => {
  cy.visit('/')
})

import { all_screenshots, all_compareviews } from '../support/screenshots.config.js'

describe(`Take plot screenshots`, () => {
  all_screenshots.forEach( (run) => {
    it(`Screenshot for ${run}`, () => {
        cy.run(run)

        // ImagePane requires an additional rerender for the image to adjust to the Pane size correctly
        if (run.startsWith("image_"))
            cy.wait(300)

        cy
          .get('.content')
          .screenshot(run, {overwrite: true})
    })
  })
})


describe(`Take compare-view screenshots`, () => {
  all_compareviews.forEach( (run) => {
    it(`Screenshot for ${run}`, () => {

        var num_runs = 3;

        var envs = []
        for (var i=0; i<num_runs; i++) {
            var env = run + "_" + i + "_" + Cypress._.random(0, 1e6);
            cy.run(run, {env:env, open: false, seed:42+i, args: [run], asyncrun: i != num_runs - 1})
            envs.push(env);
        }
        cy.close_envs();
        for (var i=0; i<num_runs; i++) {
            cy.open_env(envs[i]);
        }

        cy
          .get('.content').first()
          .screenshot("compare_"+run, {overwrite: true})
    })
  })
})


describe(`Take screenshot for PlotPane functions`, () => {

  it('Screenshot for Line Smoothing', () => {
      var run = "line_smoothing"
      var env1 = run + "_1_" + Cypress._.random(0, 1e6)
      var env2 = run + "_2_" + Cypress._.random(0, 1e6)
      cy.run('plot_line_basic', {env: env1, args: ["'Line smoothing'", 100], open:false})
      cy.run('plot_line_basic', {env: env2, args: ["'Line smoothing'", 100], seed:43})
      cy.open_env(env1);
      cy.get('button[title="smooth lines"]').click()
      cy.get('input[type="range"]')
          .then(($range) => {
            const range = $range[0]; // get the DOM node
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(range, 100); // set the value manually
            range.dispatchEvent(new Event('input', { value: 0, bubbles: true })); // now dispatch the event
          })
       cy
        .get('.content').first()
        .screenshot(run, {overwrite: true})
  })

  it('Screenshot for PropertyChnage (Line Plot)', () => {
      cy.run("plot_line_basic")
      cy.get('button[title="properties"]').click()

      // change some settings
      const change = (key, val) => cy.get('td.table-properties-name').contains(key).siblings('td.table-properties-value').find('input').clear().type(val);

      // plot settings
      change('name', 'a line')
      change('type', 'bar')
      change('opacity', '0.75')
      change('marker.line.width', '5')
      change('marker.line.color', '#0FF')

      // layout settings
      change('margin.l', '10')
      change('margin.r', '10')
      change('margin.b', '10')
      change('margin.t', '10')
      change('xaxis.type', 'log')

      // apply settings
      cy.get('button[title="properties"]').click()

      const run = "change-properties"
      cy
        .get('.content').first()
        .screenshot(run, {overwrite: true})
  })
})
