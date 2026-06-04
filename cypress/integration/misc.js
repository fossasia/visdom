before(() => {
  cy.visit('/')
})


describe('Misc Tests', () => {
  it('plot_special_graph', () => {
      cy.run('plot_special_graph')
      cy.get('svg line').should('have.length', 6)
      cy.get('svg path').should('have.length', 6)
      cy.get('svg text').should('have.length', 12)
      cy.get('svg g').should('have.length', 6)
  })
})

