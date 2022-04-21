before(() => {
  cy.visit('/')
})

import { all_screenshots, all_compareviews } from '../support/screenshots.config.js'

describe(`Take plot screenshots`, () => {
  all_screenshots.forEach( (run) => {
    it(`Screenshot for ${run}`, () => {
        cy.run(run)
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


describe(`Take line smoothing screenshot`, () => {
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
})
