
describe('Test Setup', () => {
  it('successfully loads', () => {
    cy.visit('/')
  })

  it('server is online', () => {
    cy.visit('/')
    cy.contains('online')
  });

  it('manual server reconnect', () => {
    cy.visit('/').wait(1000)
    cy.contains('online').click()
    cy.contains('offline').click()
    cy.contains('online').click()
    cy.contains('offline').click()
    cy.contains('online').click()
    cy.contains('offline').click()
    cy.contains('online')
  })

  it('tree selection opens & shows main', () => {
    cy.visit('/')
    cy.get('.rc-tree-select').click()
    cy.get('.rc-tree-select-tree').contains('main')
  })

  it('env selection works', () => {
    cy.visit('/').wait(1000)
    cy.get('.rc-tree-select [title="main"]').should('exist')
    cy.get('.rc-tree-select').contains('main').trigger('mouseover').wait(100);
    cy.get('.rc-tree-select .rc-tree-select-selection__choice__remove').click({force: true})
    cy.get('.rc-tree-select [title="main"]').should('not.exist')
    cy.get('.rc-tree-select').click()
    cy.get('.rc-tree-select-tree').contains('main').click()
    cy.get('.rc-tree-select [title="main"]').should('exist')
    cy.get('.rc-tree-select-selection__clear').click({force: true}) // bug in ui: rc-tree-select should never be covered
    cy.get('.rc-tree-select [title="main"]').should('not.exist')
  })
})
