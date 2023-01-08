before(() => {
  cy.visit('/')
})

const basic_examples = [
    ["TextPane", "text_basic"],
    ["ImagePane", "image_basic"],
    ["Line Plot", "plot_line_basic"],
    ["Bar Plot", "plot_bar_basic"],
    ["Scatter Plot", "plot_scatter_basic"],
    ["Surface Plot", "plot_surface_basic"],
    ["Box Plot", "plot_special_boxplot"],
    ["Quiver Plot", "plot_special_quiver"],
    // ["Mesh Plot", "plot_special_mesh"], // disabled due to webgl
    ["Graph Plot", "plot_special_graph"],
    ["Matplotlib Plot", "misc_plot_matplot"],
    ["Latex Plot", "misc_plot_latex"],
    ["Video Pane", "misc_video_tensor"],
    // ["Audio Pane", "misc_audio_basic"], // bug: disabled due to inconsistent resize
    ["Properties Pane", "properties_basic"]
];

basic_examples.forEach( (setting) => {
    const [ type, basic_example ] = setting;
    describe(`Test Pane Actions on ${type}`, () => {

      it(`Open Single ${type}`, () => {
          cy.run(basic_example)
          cy
            .get('.layout .window')
            .should('have.length', 1);
      })

      it('Open Some More Panes', () => {
          var env = basic_example + "_" + Cypress._.random(0, 1e6);
          cy.run(basic_example, {env:env, open:false})
          cy.run(basic_example, {env:env, open:false})
          cy.run(basic_example, {env:env, open:false})
          cy.run(basic_example, {env:env})
            .get('.layout .window')
            .should('have.length', 4);
      })

      it('Drag & Drop Pane to 2nd Position', () => {

          const targetpos = basic_example == "text_basic" ? 263 : basic_example == "image_basic" ? 276 : basic_example == "misc_plot_matplot" || basic_example == "plot_special_graph" ? 10: basic_example == "misc_video_tensor" ? 263 : basic_example == "misc_audio_basic" ? 350 : basic_example == "properties_basic" ? 263 :390

          cy
            .get('.layout .react-grid-item').first().should('have.css', 'transform', 'matrix(1, 0, 0, 1, 10, 10)')
            .find('.bar')
            .trigger('mousedown', { button: 0 })
            .trigger('mousemove', {
                 clientX: 600,
                 clientY: 0,
            })
            .trigger('mouseup', { button: 0 })
            .get('[data-original-title="Repack"]')
            .click()
            .get('.layout .react-grid-item').first().should('have.css', 'transform', `matrix(1, 0, 0, 1, ${targetpos}, 10)`)
      })


      let height, width, height2, width2, height3, width3, height4, width4;
      [ height2, width2 ] = [ 425, 321 ]; // resize to
      [ height3, width3 ] = [ 410, 307]; // grid-corrected size
      if (basic_example == "text_basic") {
          [ height, width ] = [ 290, 243 ];
          [ height4, width4 ] = [ height, width];
      } else if (basic_example == "image_basic") {
          [ height, width ] = [ 545, 256 ];
          [ height4, width4 ] = [ 545, width];
      } else if (basic_example == "misc_plot_matplot") {
          [ height, width ] = [ 500, 622 ];
          [ height4, width4 ] = [ 500, width];
      } else if (basic_example == "plot_special_graph") {
          [ height, width ] = [ 515, 500 ];
          [ height4, width4 ] = [ 515, width];
      } else if (basic_example == "misc_video_tensor") {
          [ height, width ] = [ 290, 243 ];
          [ height4, width4 ] = [ 290, width];
      } else if (basic_example == "misc_audio_basic") {
          [ height, width ] = [ 95, 330 ];
          [ height4, width4 ] = [ 410, 307]; // also a bug in the ui
      } else if (basic_example == "properties_basic") {
          [ height, width ] = [ 290, 243 ];
          [ height4, width4 ] = [ height, width];
      } else {
          [ height, width ] = [ 350, 370];
          [ height4, width4 ] = [ height, width];
      }

      it('Check Pane Size', () => {
          cy
            .get('.layout .react-grid-item').first()
            .should('have.css', 'height', height + 'px')
            .should('have.css', 'width', width + 'px')
      })

      it('Resize Pane', () => {
          cy
            .get('.layout .react-grid-item').first()
            .find('.react-resizable-handle')
            .trigger('mousedown', { button: 0 })
            .trigger('mousemove', width2 - width, height2 - height, { force: true })
            .trigger('mouseup', { button: 0, force: true })
            .get('.layout .react-grid-item').first()
            .should('have.css', 'height', height3 + 'px')
            .should('have.css', 'width', width3 + 'px')
      })

      it('Resize Pane Reset', () => {
          cy
            .get('.layout .react-grid-item').first()
            .find('.react-resizable-handle')
            .dblclick()
            .get('.layout .react-grid-item').first()
            .should('have.css', 'height', height4 + 'px')
            .should('have.css', 'width', width4 + 'px')
      })

      it('Close Pane', () => {
          cy
            .get('.layout .react-grid-item').first()
            .find('button[title="close"]')
            .click()

          cy
            .get('.layout .react-grid-item')
            .should('have.length', 3);
      })
    })

});


describe('Test Pane Filter', () => {
  it('Open Some Panes', () => {
      var env = 'pane_basic' + Cypress._.random(0, 1e6);
      cy.run('text_basic', {env:env, open:false, args:['"pane1 tag1"']})
      cy.run('text_basic', {env:env, open:false, args:['"pane2 tag1 tag2"']})
      cy.run('text_basic', {env:env, open:false, args:['"pane3 tag2"']})
      cy.run('text_basic', {env:env, args:['"pane4 tag2"']})
      cy.get('.layout .window')
        .should('have.length', 4);
  })

  it('Filter Test 1', () => {
      cy.get('[data-cy="filter"]').type('tag1', {force: true})
      cy.get('.layout .window:visible')
        .should('have.length', 2);
  })

  it('Filter Test 2', () => {
      cy.get('[data-cy="filter"]').clear().type('tag2', {force: true})
      cy.get('.layout .window:visible')
        .should('have.length', 3);
  })

  it('Filter Test 3', () => {
      cy.get('[data-cy="filter"]').clear().type('pane3', {force: true})
      cy.get('.layout .window:visible')
        .should('have.length', 1);
  })

  it('Filter Test Regex', () => {
      cy.get('[data-cy="filter"]').clear().type('pane3|pane2', {force: true})
      cy.get('.layout .window:visible')
        .should('have.length', 2);
  })
})


