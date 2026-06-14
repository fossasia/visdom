const exportButton = 'button[data-original-title="Export as HTML"]';

beforeEach(() => {
  cy.visit('/');
});

describe('Test Export Env as HTML', () => {
  const stubBlobCapture = () => {
    cy.window().then((win) => {
      cy.stub(win.URL, 'createObjectURL')
        .callsFake((blob) => {
          win.__exportedBlob = blob;
          return 'blob:fake-url-for-testing';
        })
        .as('createObjectURL');
    });
  };


  const readCapturedHtml = () => {
    return cy.window().then((win) => {
      expect(win.__exportedBlob, '__exportedBlob should be set after export').to
        .exist;
      return win.__exportedBlob.text();
    });
  };

  it('Export button is disabled when no env is open', () => {
    cy.close_envs();
    cy.get(exportButton).should('be.disabled');
  });


  it('Downloads a valid HTML file when panes are available', () => {
    const env = 'export_test_' + Cypress._.random(0, 1e6);
    cy.run('text_basic', { env });
    cy.get('.layout .window').should('have.length', 1);

    stubBlobCapture();
    cy.get(exportButton).should('not.be.disabled').click();

    cy.get('@createObjectURL').should('have.been.calledOnce');

    readCapturedHtml().then((html) => {
      expect(html).to.include('<!DOCTYPE html>');
      expect(html).to.include('id="board"');
      expect(html).to.include('plotly');
      expect(html).to.include('const DATA =');
      expect(html).to.include('const IDS  =');
      expect(html).to.include(env);
    });
  });


  it('Exported HTML contains pane data for plot', () => {
    const env = 'export_content_' + Cypress._.random(0, 1e6);
    cy.run('plot_line_basic', { env });
    cy.get('.layout .window').should('have.length', 1);

    stubBlobCapture();
    cy.get(exportButton).click();

    readCapturedHtml().then((html) => {
      expect(html).to.include('"type"');
      expect(html).to.include('"data"');
      expect(html).to.include(env);
    });
  });


  it('Shows alert when all panes are closed before export', () => {
    const env = 'export_empty_' + Cypress._.random(0, 1e6);
    cy.run('text_basic', { env });
    cy.get('.layout .window').should('have.length', 1);

    cy.get('.layout .react-grid-item')
      .first()
      .find('button[title="close"]')
      .click();
    cy.get('.layout .react-grid-item').should('have.length', 0);

    cy.window().then((win) => {
      cy.stub(win, 'alert').as('alertStub');
    });

    cy.get(exportButton).should('not.be.disabled').click();

    cy.get('@alertStub').should(
      'have.been.calledWith',
      'No panes available to export.'
    );
  });
});
