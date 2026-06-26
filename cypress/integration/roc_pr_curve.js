before(() => {
  cy.visit('/');
});

describe('ROC / PR Curve Pane', () => {
  it('roc_curve_basic', () => {
    cy.run('plot_roc_curve');

    cy.get('.layout .window').should('have.length', 1);

    cy.get('.content').contains('ROC Curve Example');

    cy.get('.content .scatterlayer path.js-line').should('have.length', 2);

    cy.get('.content').contains('False Positive Rate');
    cy.get('.content').contains('True Positive Rate');

    cy.get('.content').contains('Chance');
  });

  it('pr_curve_basic', () => {
    cy.run('plot_pr_curve');

    cy.get('.layout .window').should('have.length', 1);

    cy.get('.content').contains('PR Curve Example');

    cy.get('.content .scatterlayer path.js-line').should('have.length', 2);

    cy.get('.content').contains('Recall');
    cy.get('.content').contains('Precision');

    cy.get('.content').contains('Baseline');
  });

  it('roc_curve_precomputed', () => {
    cy.run('plot_roc_precomputed');

    cy.get('.layout .window').should('have.length', 1);
    cy.get('.content').contains('ROC Curve (Precomputed)');

    cy.get('.content .scatterlayer path.js-line').should('have.length', 2);
  });

  it('roc_pr_curve_close', () => {
    cy.run('plot_roc_curve');
    cy.get('.layout .react-grid-item')
      .first()
      .find('button[title="close"]')
      .click();
    cy.get('.layout .window').should('have.length', 0);
  });
});
