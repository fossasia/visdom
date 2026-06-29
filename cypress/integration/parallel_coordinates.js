before(() => {
  cy.visit('/');
});

describe('Parallel Coordinates Pane', () => {
  it('parallel_coordinates_basic', () => {
    cy.run('plot_special_parallel_coordinates');

    cy.get('.layout .window').should('have.length', 1);

    cy.get('.content').contains('Experiment Comparison');
  });

  it('parallel_coordinates_close', () => {
    cy.run('plot_special_parallel_coordinates');
    cy.get('.layout .react-grid-item')
      .first()
      .find('button[title="close"]')
      .click();
    cy.get('.layout .window').should('have.length', 0);
  });
});
