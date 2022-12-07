before(() => {
  cy.visit('/');
});

const path = require('path');

describe('Text Pane', () => {
  it('text_basic', () => {
    cy.run('text_basic');
  });

  it('text_update', () => {
    cy.run('text_update')
      .get('.layout .react-grid-item')
      .first()
      .contains('Hello World! More text should be here')
      .contains('And here it is');
  });

  it('check download button', () => {
    cy.run('text_update')
      .get('.layout .react-grid-item')
      .first()
      .find('button[title="save"]')
      .click();
    const downloadsFolder = Cypress.config('downloadsFolder');
    cy.readFile(path.join(downloadsFolder, 'visdom_text.txt')).should('exist');
  });

  it('text_callbacks', () => {
    cy.run('text_callbacks', { asyncrun: true });
    cy.get('.window .content')
      .first()
      .type('checking callback :({backspace})', { delay: 200 }) // requiring a delay is a bug
      .contains('checking callback :)');
  });

  it('text_close', () => {
    cy.run('text_close');
    cy.get('.layout .window').should('have.length', 0);
  });
});
