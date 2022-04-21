before(() => {
  cy.visit('/')
})

import { all_screenshots } from '../support/screenshots.config.js'

describe(`Compare plot screenshots`, () => {
  all_screenshots.forEach( (run) => {
    it(`Compare screenshot of ${run}`, () => {
        cy.run(run)

        const diff_src = Cypress.config("screenshotsFolder") + "/" + "screenshots.diff.js" + "/" + run + ".png";
        const img1_src = Cypress.config("screenshotsFolder") + "_init/" + "screenshots.init.js" + "/" + run + ".png";
        const img2_src = Cypress.config("screenshotsFolder") + "/" + Cypress.spec.name + "/" + run + ".png";

        cy
          .get('.content').first()
          .screenshot(run, {overwrite: true})
        cy.task('numDifferentPixels', {src1: img1_src, src2: img2_src, diffsrc: diff_src, threshold: 0.1}).should('equal', 0)
    })
  })
})



