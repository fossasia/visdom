before(() => {
  cy.visit('/')
})

const path = require("path");

describe('Properties Pane', () => {

  it('check download button', () => {
      cy.run('properties_basic')
          .get('.layout .react-grid-item').first()
          .find('button[title="save"]').click()
      const downloadsFolder = Cypress.config("downloadsFolder");
      cy.readFile(path.join(downloadsFolder, "visdom_properties.json")).should("exist");
  });


  it('properties_callbacks', () => {
      cy.run('properties_callbacks', {asyncrun: true})

      cy.get('input[value="initial"]').first().clear().type("changed{enter}")
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Text input => changed")

      cy.get('input[value="12"]').first().clear().type("42{enter}")
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Number input => 42")

      cy.get('button').contains("Start").click()
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Button => clicked")

      cy.get('input[value="on"]').first().click()
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Checkbox => False")

      cy.get('select').first().select('Red').select('Blue')
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Select => 0")

      cy.get('select').first().select('Blue')
      cy.get('.layout .react-grid-item .content-text').first().contains("Updated: Select => 2")

  })

})
