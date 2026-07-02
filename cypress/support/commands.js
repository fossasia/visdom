// ***********************************************
// This example commands.js shows you how to
// create various custom commands and overwrite
// existing commands.
//
// For more comprehensive examples of custom
// commands please read more here:
// https://on.cypress.io/custom-commands
// ***********************************************
//
//
// -- This is a parent command --
// Cypress.Commands.add('login', (email, password) => { ... })
//
//
// -- This is a child command --
// Cypress.Commands.add('drag', { prevSubject: 'element'}, (subject, options) => { ... })
//
//
// -- This is a dual command --
// Cypress.Commands.add('dismiss', { prevSubject: 'optional'}, (subject, options) => { ... })
//
//
// -- This will overwrite an existing command --
// Cypress.Commands.overwrite('visit', (originalFn, url, options) => { ... })
//
//

import '@4tw/cypress-drag-drop';

Cypress.Commands.add('run', (name, opts) => {
  var saveto =
    opts && 'env' in opts ? opts['env'] : name + '_' + Cypress._.random(0, 1e6);
  var argscli = '';
  if (opts && 'args' in opts) {
    argscli =
      ' -arg ' +
      opts['args']
        .map((arg) => {
          let s = String(arg);
          if (s.includes(' ') || s.includes('"') || s.includes("'")) {
            return '"' + s.replace(/"/g, '\\"') + '"';
          }
          return s;
        })
        .join(' ');
  }
  var seed = opts && 'seed' in opts ? ' -seed ' + opts['seed'] : '';
  if (!opts || !('asyncrun' in opts) || !opts['asyncrun'])
    cy.exec(
      `python example/demo.py -port 8098 -testing -run ${name} -env ${saveto} ${seed} ${argscli}`
    );
  else
    cy.task('asyncrun', {
      run: name,
      env: saveto,
      seed: opts && 'seed' in opts ? opts['seed'] : undefined,
      args: opts && 'args' in opts ? opts['args'] : [],
    });

  if (!opts || !('open' in opts) || opts['open']) {
    cy.close_envs();
    cy.open_env(saveto);
  }
});

Cypress.Commands.add('close_envs', () => {
  cy.get('body').then(($body) => {
    const $navbar = $body.find('.navbar-form');
    if ($navbar.length > 0) {
      const $clear = $navbar.find('.rc-tree-select-clear');
      if ($clear.length > 0) {
        cy.wrap($clear).click({ force: true, multiple: true });
      }
    }
  });
});

Cypress.Commands.add('expand_all_env_groups', () => {
  cy.get('.rc-tree-select-tree').then(($tree) => {
    const closed_group = '.rc-tree-select-tree-switcher_close';
    if ($tree.find(closed_group).length > 0) {
      cy.get(closed_group).each(($el) => {
        cy.wrap($el).click({ force: true });
        cy.wait(150);
      });
    }
  });
});

Cypress.Commands.add('close_env_dropdown', () => {
  cy.get('body').type('{esc}');
});

Cypress.Commands.add('open_env', (name) => {
  cy.get('.navbar-form .rc-tree-select').first().click();

  // Wait for the tree to contain either the env name (if root level) or the group name (if grouped)
  const idx = name.indexOf('_');
  const expectedText = idx > 0 ? name.substring(0, idx) : name;
  cy.get('.rc-tree-select-tree').contains(expectedText).should('exist');

  cy.expand_all_env_groups();
  cy.get('.rc-tree-select-tree').contains(name).click({ force: true });
  cy.close_env_dropdown();
});

Cypress.Commands.add('waitForPlotRender', () => {
  cy.get('.content', { timeout: 20000 }).should('be.visible');
  cy.wait(800);
});

Cypress.Commands.add('waitForMathJax', () => {
  cy.wait(2000);
});
