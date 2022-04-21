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

Cypress.Commands.add('run', (name, opts) => {
  var saveto = (opts && "env" in opts) ? opts["env"] : name + "_" + Cypress._.random(0, 1e6);
  var argscli = (opts && "args" in opts) ? ('-arg '+opts["args"].join(' ')) : '';
  if (!opts || !("asyncrun" in opts) || !opts["asyncrun"])
      cy.exec(`python example/demo.py -port 8098 -testing -run ${name} -env ${saveto} ${argscli}`);
  else
      cy.task('asyncrun', `python example/demo.py -testing -port 8098 -run ${name} -env ${saveto}` + argscli)

  if (!opts || !("open" in opts) || opts["open"]) {
      cy.close_envs();
      cy.open_env(saveto);
  }
});

Cypress.Commands.add('close_envs', () => {
    cy.get('.rc-tree-select-selection__clear').click()
});

Cypress.Commands.add('open_env', (name) => {
    cy.get('.rc-tree-select').click()
    cy.get('.rc-tree-select-tree').contains(name).click()
    cy.get('.rc-tree-select').click({force: true}) // ignore any elements that might cover the list at this point
});

