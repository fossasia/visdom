/* eslint-disable no-undef */
before(() => {
  cy.visit('/');
});

const envmodal = 'div[aria-label="Environment Management Modal"] ';
const envbutton = 'button[data-original-title="Manage Environments"] ';
const viewmodal = 'div[aria-label="Layout Views Management Modal"] ';
const viewbutton = 'button[data-original-title="Manage Views"] ';
const viewselect = 'div[aria-label="View:"] ';

describe('Test Env Modal', () => {
  var env = 'text_fork' + '_' + Cypress._.random(0, 1e6);

  it('Env Modal opens & closes', () => {
    cy.get(envmodal).should('not.exist');
    cy.get(envbutton).click();
    cy.get(envmodal).should('exist');
    cy.get(envmodal).type('{esc}');
    cy.get(envmodal).should('not.exist');
  });

  it('Env Modal forks envs', () => {
    // initialize any env
    cy.run('text_fork_part1', { env: env })
      .get('.layout .react-grid-item')
      .first()
      .contains('This text will change. Fork to the rescue!');

    // fork the env at this point
    cy.get(envbutton).click();
    cy.get(envmodal + 'input').type('_fork');
    cy.contains('button', 'fork').click();
    cy.get(envmodal).type('{esc}');

    // apply a change to the same env
    cy.run('text_fork_part2', { env: env })
      .get('.layout .react-grid-item')
      .first()
      .contains('Changed text.');

    // check if fork is still the old one
    cy.close_envs();
    cy.open_env(env + '_fork')
      .get('.layout .react-grid-item')
      .first()
      .contains('This text will change. Fork to the rescue!');

    // check again original just to be sure
    cy.close_envs();
    cy.open_env(env)
      .get('.layout .react-grid-item')
      .first()
      .contains('Changed text.');
  });

  it('Remove Env', () => {
    // delete fork
    cy.get(envbutton).click();
    cy.get(envmodal + 'select').select(env + '_fork');
    cy.contains('button', 'Delete').click();
    cy.get(envmodal).type('{esc}');

    // check that fork does not exist anymore
    cy.get('.rc-tree-select').click();
    cy.get('span[title="' + env + '"]').should('exist');
    cy.get('span[title="' + env + '_fork"]').should('not.exist');

    // all windows should be closed now as well
    // TODO: current implementation does not close windows automatically

    // remove also the original env & check if it is removed from the env-list
    // TODO: current implementation does not allow to remove unsaved envs
    // cy.get(envbutton).click();
    // cy.get(envmodal + 'select').select(env);
    // cy.contains('button', 'Delete').click();
    // cy.get(envmodal).type('{esc}');
    // check that the env does not exist anymore
    // cy.get('.rc-tree-select').click();
    // cy.get('span[title="' + env + '"]').should('not.exist');
  });
});

describe('Test View Modal', () => {
  it('View Modal opens & closes', () => {
    cy.get(viewmodal).should('not.exist');
    cy.get(viewbutton).click();
    cy.get(viewmodal).should('exist');
    cy.get(viewmodal).type('{esc}');
    cy.get(viewmodal).should('not.exist');
  });

  it('View Modal save view', () => {
    var env = 'view_modal_' + Cypress._.random(0, 1e6);

    // initialize any env
    cy.run('text_basic', { env: env }).wait(500);
    cy.run('image_basic', { env: env, open: false }).wait(500);
    cy.run('plot_line_basic', { env: env, open: false }).wait(500);
    cy.run('plot_bar_basic', { env: env, open: false }).wait(500);

    // save the view at this point
    cy.get(viewbutton).click();
    cy.get(viewmodal + 'input')
      .clear()
      .type('first');
    cy.contains('button', 'fork').click();
    cy.get(viewmodal).type('{esc}');

    // apply a change to the same view
    cy.get('.layout .react-grid-item')
      .first()
      .find('.bar')
      .trigger('mousedown', { button: 0 })
      .trigger('mousemove', {
        clientX: 1000,
        clientY: 300,
      })
      .trigger('mouseup', { button: 0 });

    // save the view at this point
    cy.get(viewbutton).click();
    cy.get(viewmodal + 'input')
      .clear()
      .type('second');
    cy.contains('button', 'fork').click();
    cy.get(viewmodal).type('{esc}');

    // check first view positions
    cy.get(viewselect + 'button#viewDropdown').click();
    cy.get(viewselect + "a[href='#first']").click();
    cy.get('.react-grid-layout > div')
      .eq(0)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(1)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 263, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(2)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 529, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(3)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 565)`);

    // check second view positions
    cy.get(viewselect + 'button#viewDropdown').click();
    cy.get(viewselect + "a[href='#second']").click();
    cy.get('.react-grid-layout > div')
      .eq(0)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 390, 370)`);
    cy.get('.react-grid-layout > div')
      .eq(1)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(2)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 565)`);
    cy.get('.react-grid-layout > div')
      .eq(3)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 276, 10)`);

    // check first view positions
    cy.get(viewselect + 'button#viewDropdown').click();
    cy.get(viewselect + "a[href='#first']").click();
    cy.get('.react-grid-layout > div')
      .eq(0)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(1)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 263, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(2)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 529, 10)`);
    cy.get('.react-grid-layout > div')
      .eq(3)
      .should('have.css', 'transform', `matrix(1, 0, 0, 1, 10, 565)`);
  });

  it('Remove additional View again', () => {
    // delete view first and second
    cy.get(viewbutton).click();
    cy.get(viewmodal + 'select').select('first');
    cy.contains('button', 'Delete').click();
    cy.get(viewmodal + 'select').select('second');
    cy.contains('button', 'Delete').click();
    cy.get(viewmodal).type('{esc}');

    // check that current view cannot be removed
    cy.get(viewbutton).click();
    cy.get(viewmodal + 'select').select('current');
    cy.contains('button', 'Delete').should('be.disabled');
    cy.get(viewmodal).type('{esc}');
  });
});
