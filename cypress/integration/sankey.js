before(() => {
  cy.visit('/');
});


describe('Sankey Plot', () => {
  it('renders a single sankey pane', () => {
    cy.run('plot_special_sankey');
    cy.get('.layout .window').should('have.length', 1);
    // PlotPane mounts a plotly graph div with an SVG inside it
    cy.get('.layout .window .plotly-graph-div').should('exist');
    cy.get('.layout .window .plotly-graph-div svg').should('exist');
  });

  it('renders every node label from the demo', () => {
    cy.run('plot_special_sankey');
    // demo labels: raw -> cleaned -> labeled -> {train, val, test}
    // plotly draws node labels as real <text> nodes, so they are queryable
    ['raw', 'cleaned', 'labeled', 'train', 'val', 'test'].forEach((label) => {
      cy.get('.layout .window').contains(label).should('exist');
    });
  });
});
