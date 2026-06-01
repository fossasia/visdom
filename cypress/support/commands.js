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
  var saveto = (opts && "env" in opts) ? opts["env"] : name + "_" + Cypress._.random(0, 1e6);
  var argscli = '';
  if (opts && "args" in opts) {
      argscli = ' -arg ' + opts["args"].map(arg => {
          let s = String(arg);
          if (s.includes(' ') || s.includes('"') || s.includes("'")) {
              return '"' + s.replace(/"/g, '\\"') + '"';
          }
          return s;
      }).join(' ');
  }
  var seed = (opts && "seed" in opts) ? (' -seed '+opts["seed"]) : '';
  if (!opts || !("asyncrun" in opts) || !opts["asyncrun"])
      cy.exec(`python example/demo.py -port 8098 -testing -run ${name} -env ${saveto} ${seed} ${argscli}`);
  else
      cy.task('asyncrun', {
          run: name,
          env: saveto,
          seed: (opts && "seed" in opts) ? opts["seed"] : undefined,
          args: (opts && "args" in opts) ? opts["args"] : [],
      })

  if (!opts || !("open" in opts) || opts["open"]) {
      cy.close_envs();
      cy.open_env(saveto);
  }
});

Cypress.Commands.add('close_envs', () => {
    cy.get('body').then($body => {
        if ($body.find('.rc-tree-select-selection__clear').length > 0) {
            cy.get('.rc-tree-select-selection__clear').click()
        }
    })
});

Cypress.Commands.add('expand_all_env_groups', () => {
    cy.get('.rc-tree-select-tree').then($tree => {
        var closed_group = '.rc-tree-select-tree-switcher_close';
        if ($tree.find(closed_group).length > 0) {
            cy.get(closed_group).each($el => {
                cy.wrap($el).click();
            });
        }
    });
});

Cypress.Commands.add('close_env_dropdown', () => {
    cy.get('.rc-tree-select').click({force: true});
});

Cypress.Commands.add('open_env', (name) => {
    cy.get('.rc-tree-select').click();
    cy.expand_all_env_groups();
    cy.get('.rc-tree-select-tree').contains(name).click();
    cy.close_env_dropdown();
});

