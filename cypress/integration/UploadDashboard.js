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

  it('should successfully upload valid dashboard JSON and set it as current environment', () => {
    cy.intercept('POST', '/upload_env', (req) => {
      req.continue((res) => {
        res.delay = 1000;
      });
    }).as('uploadRequest');

    cy.window().then((win) => {
      cy.stub(win, 'alert').as('alertStub');
    });

    cy.fixture('test.json').then((fileContent) => {
      cy.get('input[type="file"]').selectFile(
        {
          contents: fileContent,
          fileName: 'test.json',
          mimeType: 'application/json',
        },
        { force: true }
      );

      cy.get('button .glyphicon-upload').parent('button').click();
      cy.wait('@uploadRequest');
      cy.get('@alertStub', { timeout: 15000 }).should('have.been.called');

      cy.window().then((win) => {
        const envIDs = JSON.parse(win.localStorage.getItem('envIDs'));
        expect(envIDs).to.be.an('array');
        expect(envIDs[0]).to.match(/^uploaded_/);
      });
    });
  });
});
