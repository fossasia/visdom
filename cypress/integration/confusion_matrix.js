before(() => {
  cy.visit('/');
});

describe('Confusion Matrix Pane', () => {
  it('confusion_matrix_basic', () => {
    cy.run('plot_confusion_matrix_basic');

    cy.get('.layout .window').should('have.length', 1);

    cy.get('.content').contains('Confusion Matrix (Basic)');

    cy.get('.content g.heatmaplayer').should('exist');

    cy.get('.content text.annotation-text').should('have.length', 9);

    cy.get('.content').contains('Predicted');
    cy.get('.content').contains('Actual');
  });

  it('confusion_matrix_precomputed', () => {
    cy.run('plot_confusion_matrix_precomputed');

    cy.get('.layout .window').should('have.length', 1);
    cy.get('.content').contains('Confusion Matrix (Precomputed)');

    cy.get('.content').contains('cat');
    cy.get('.content').contains('dog');
    cy.get('.content').contains('bird');
  });

  it('confusion_matrix_normalized', () => {
    cy.run('plot_confusion_matrix_normalized');

    cy.get('.layout .window').should('have.length', 1);
    cy.get('.content').contains('Confusion Matrix (Normalized by Row)');

    cy.get('.content text.annotation-text')
      .filter(':contains("%")')
      .should('have.length.greaterThan', 0);
  });

  it('confusion_matrix_close', () => {
    cy.run('plot_confusion_matrix_basic');
    cy.get('.layout .react-grid-item')
      .first()
      .find('button[title="close"]')
      .click();
    cy.get('.layout .window').should('have.length', 0);
  });
});
