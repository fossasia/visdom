describe('Visdom - Upload Dashboard JSON Feature', () => {
  beforeEach(() => {
    cy.visit('/');
    cy.get('.visdom-title', { timeout: 15000 }).should('be.visible');
  });

  it('should display Upload JSON button', () => {
    cy.get('button .glyphicon-upload')
      .should('be.visible')
      .parent('button')
      .should('be.visible');
  });

  it('should reject non-JSON files', () => {
    cy.get('input[type="file"]').selectFile(
      {
        contents: Cypress.Buffer.from('This is not json'),
        fileName: 'test.txt',
        mimeType: 'text/plain',
      },
      { force: true }
    );
    cy.get('button .glyphicon-upload').parent('button').click();
    cy.on('window:alert', (str) => {
      expect(str.toLowerCase()).to.contain('json');
    });
  });
});
