before(() => {
  cy.visit('/');
});

const path = require('path');
const win_selector = '.layout .react-grid-item';
const container_selector = `${win_selector} .content > div`;
const img_selector = `${container_selector} img`;

describe('Image Pane', () => {
  it('image_basic', () => {
    cy.run('image_basic')
      .get(win_selector)
      .first()
      .find('img')
      .should('have.length', 1);
  });

  it('Image Movement (Alt + Wheel or Drag)', () => {
    // check default position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '0px')
      .should('have.css', 'left', '0px');

    // scroll a bit
    cy.get(img_selector)
      .first()
      .trigger('wheel', {
        altKey: true,
        deltaY: 20,
        deltaX: 30,
        bubbles: true,
      });

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '-50px')
      .should('have.css', 'left', '-50px');

    // check drag and drop
    cy.get(img_selector)
      .first()
      .trigger('mousemove', {
        button: 0,
        clientX: 120,
        clientY: 300,
      })
      .trigger('dragover');

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '256px')
      .should('have.css', 'left', '38px');
  });

  it('Image Zoom (Ctrl + Wheel)', () => {
    // scroll a bit
    cy.get(img_selector)
      .first()
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .should('have.attr', 'width', '157px')
      .should('have.attr', 'height', '314px');

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '276.786px')
      .should('have.css', 'left', '81.5211px');
  });

  it('Image Reset (Double-Click)', () => {
    cy.get(img_selector)
      .first()
      .dblclick()
      .should('have.attr', 'width', '257px')
      .should('have.attr', 'height', '514px');

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '0px')
      .should('have.css', 'left', '0px');
  });

  it('image_basic download', () => {
    cy.run('image_basic')
      .get(img_selector)
      .parents(win_selector)
      .first()
      .find('button[title="save"]')
      .click();
    const downloadsFolder = Cypress.config('downloadsFolder');
    cy.readFile(path.join(downloadsFolder, 'Random!.jpg')).should('exist');
  });

  it('image_save_jpeg', () => {
    cy.run('image_save_jpeg')
      .get(img_selector)
      .parents(win_selector)
      .first()
      .find('button[title="save"]')
      .click();
    const downloadsFolder = Cypress.config('downloadsFolder');
    cy.readFile(path.join(downloadsFolder, 'Random image as jpg!.jpg')).should(
      'exist'
    );
  });

  it('image_history', () => {
    cy.run('image_history', { asyncrun: true });

    cy.get(img_selector)
      .should('have.length', 1)
      .then((src) => {
        const src1 = src;
        // image exists
        cy.get('.layout .react-grid-item .widget input[type="range"]')
          .first()

          // slider works
          // (bugfix for not working simpler .invoke('val', '0').invoke('input'))
          .then(($range) => {
            const range = $range[0]; // get the DOM node
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,
              'value'
            ).set;
            nativeInputValueSetter.call(range, 0); // set the value manually
            range.dispatchEvent(
              new Event('input', { value: 0, bubbles: true })
            ); // now dispatch the event
          })

          // shown image differs
          .then((src2) => {
            cy.expect(src1).to.not.equal(src2);
          });
      });
  });

  it('image_grid', () => {
    cy.run('image_grid', { asyncrun: true });
    cy.get(img_selector)
      .should('have.length', 1)
      .should('have.attr', 'width', '545px')
      .should('have.attr', 'height', '205px');
  });

  it('image_svg', () => {
    cy.run('image_svg', { asyncrun: true });
    cy.get('.window .content')
      .first()
      .find('ellipse')
      .should('have.length', 1)
      .should('have.attr', 'cx', 80)
      .should('have.attr', 'cy', 80)
      .should('have.attr', 'rx', 50)
      .should('have.attr', 'ry', 30);
  });

  it('image_callback', () => {
    cy.run('image_callback', { asyncrun: true });
    cy.get(img_selector)
      .parents(win_selector)
      .click() // to focus the pane
      .find('img')
      .click(12, 34)
      .click(45, 67);
    cy.get('.layout .react-grid-item .content-text')
      .first()
      .contains('Coords:')
      .contains('x: 12, y: 35;') // bug: y is off by 1
      .contains('x: 45, y: 68;'); // bug: y is off by 1
  });

  it('image_callback2', () => {
    cy.run('image_callback2', { asyncrun: true });
    cy.get(img_selector)
      .type('{rightArrow}'.repeat(3))
      .type('{leftArrow}')
      .should(
        'have.attr',
        'src',
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAIAAADTED8xAAACvklEQVR4nO3TMQEAIAzAMEDs/EtAxo4mCvr0zsyBqrcdAJsMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYA0A5BmANIMQJoBSDMAaQYgzQCkGYC0D5OxAzLzmPjyAAAAAElFTkSuQmCC'
      );
  });
});
