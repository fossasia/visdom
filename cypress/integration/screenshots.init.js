before(() => {
  cy.visit('/')
})

import { all_screenshots } from '../support/screenshots.config.js'

describe(`Make plot screenshots`, () => {
  all_screenshots.forEach( (run) => {
    it(`Screenshot for ${run}`, () => {
        cy.run(run)
        cy
          .get('.content')
          .screenshot(run, {overwrite: true})
    })
  })
})


