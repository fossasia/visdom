before(() => {
  cy.visit('/');
});

const path = require('path');
const win_selector = '.layout .react-grid-item';
const container_selector = `${win_selector} .content > div`;
const img_selector = `${container_selector} img`;
const [moveX, moveY] = [12, 34]; // required for drag/drop action
const [imgWidth, imgHeight] = [255, 510]; // required for drag/drop action
const basepos = 10; // required for drag/drop action

describe('Image Pane', () => {
  it('image_basic', () => {
    cy.run('image_basic')
      .get(win_selector)
      .first()
      .find('img')
      .should('have.length', 1);
  });

  it('Image Move (Drag and Drop)', () => {
    // check new position
    cy.get(container_selector)
      .should('have.css', 'top', '0px')
      .should('have.css', 'left', '0px');

    // drag image
    cy.get(img_selector)
      .drag(img_selector, {
        source: { x: basepos, y: basepos },
        target: { x: basepos + moveX, y: basepos + moveY },
        force: true,
      })
      .wait(100);

    // check new position
    cy.get(container_selector)
      .should('have.css', 'top', `${moveY}px`)
      .should('have.css', 'left', `${moveX}px`);
    cy.get(img_selector)
      .should('have.attr', 'width', `${imgWidth}px`)
      .should('have.attr', 'height', `${imgHeight}px`);

    // drag again
    cy.get(img_selector)
      .drag(img_selector, {
        source: { x: basepos, y: basepos },
        target: { x: basepos + moveX, y: basepos + moveY },
        force: true,
      })
      .wait(100);

    // check new position
    cy.get(container_selector)
      .should('have.css', 'top', `${2 * moveY}px`)
      .should('have.css', 'left', `${2 * moveX}px`);
    cy.get(img_selector)
      .should('have.attr', 'width', `${imgWidth}px`)
      .should('have.attr', 'height', `${imgHeight}px`);
  });

  it('Image Reset (Double-Click)', () => {
    // reset image
    cy.get(img_selector).dblclick();

    // check new position & image size
    cy.get(container_selector)
      .should('have.css', 'top', '0px')
      .should('have.css', 'left', '0px');
    cy.get(img_selector)
      .should('have.attr', 'width', `${imgWidth}px`)
      .should('have.attr', 'height', `${imgHeight}px`);
  });

  it('Image Zoom From Image Corner (Ctrl + Wheel)', () => {
    // scroll a bit
    cy.get(img_selector)
      .first()
      .trigger('wheel', {
        ctrlKey: true,
        deltaY: 200,
        bubbles: true,
        clientX: 0,
        clientY: 0,
      })
      .trigger('wheel', {
        ctrlKey: true,
        deltaY: 200,
        bubbles: true,
        clientX: 0,
        clientY: 0,
      })
      .trigger('wheel', {
        ctrlKey: true,
        deltaY: 200,
        bubbles: true,
        clientX: 0,
        clientY: 0,
      })
      .trigger('wheel', {
        ctrlKey: true,
        deltaY: 200,
        bubbles: true,
        clientX: 0,
        clientY: 0,
      })
      .trigger('wheel', {
        ctrlKey: true,
        deltaY: 200,
        bubbles: true,
        clientX: 0,
        clientY: 0,
      })
      .should('have.attr', 'width', '156px')
      .should('have.attr', 'height', '312px');

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '-32.658px')
      .should('have.css', 'left', '-3.93469px');
  });

  it('Image Zoom From Image Center (Ctrl + Wheel)', () => {
    // reset image
    cy.get(img_selector).dblclick();

    // scroll a bit
    cy.get(img_selector)
      .first()
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .should('have.attr', 'width', '156px')
      .should('have.attr', 'height', '312px');

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '105.77px')
      .should('have.css', 'left', '49.9706px');
  });

  it('Image Move & Zoom', () => {
    // reset image
    cy.get(img_selector).first().dblclick();

    // check default position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '0px')
      .should('have.css', 'left', '0px');

    // scroll a bit
    cy.get(img_selector)
      .first()
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true })
      .trigger('wheel', { ctrlKey: true, deltaY: 200, bubbles: true });

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', '105.77px')
      .should('have.css', 'left', '49.9706px');
    cy.get(img_selector)
      .should('have.attr', 'width', '156px')
      .should('have.attr', 'height', '312px');

    // now drag as well
    cy.get(img_selector)
      .drag(img_selector, {
        source: { x: basepos, y: basepos },
        target: { x: basepos + moveX, y: basepos + moveY },
        force: true,
      })
      .wait(100);

    // check new position
    cy.get(container_selector)
      .first()
      .should('have.css', 'top', `139.77px`)
      .should('have.css', 'left', '61.9706px');
    cy.get(img_selector)
      .should('have.attr', 'width', '156px')
      .should('have.attr', 'height', '312px');
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
      .should('have.attr', 'width', '543px')
      .should('have.attr', 'height', '204px');
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

  let click1 = [12, 34];
  let click2 = [45, 67];
  it('image_callback', () => {
    cy.run('image_callback', { asyncrun: true });
    cy.get(img_selector)
      .parents(win_selector)
      .click() // to focus the pane
      .find('div.content')
      .click(click1[0], click1[1])
      .click(click2[0], click2[1]);
    cy.get('.layout .react-grid-item .content-text')
      .first()
      .contains('Coords:')
      .contains(`x: ${click1[0]}, y: ${click1[1]};`)
      .contains(`x: ${click2[0]}, y: ${click2[1]};`);
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
