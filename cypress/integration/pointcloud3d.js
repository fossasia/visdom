before(() => {
  cy.visit('/');
});

const win_selector = '.layout .react-grid-item';

describe('PointCloud3D Pane', () => {
  it('plot_pointcloud_basic renders a pane with a canvas', () => {
    cy.run('plot_pointcloud_basic')
      .get(win_selector)
      .should('have.length', 1);
    cy.get(win_selector)
      .first()
      .find('canvas')
      .should('have.length', 1);
    cy.get(win_selector)
      .first()
      .find('.bar')
      .contains('Point cloud (');
  });

  it('plot_pointcloud_rgb renders a pane with a canvas', () => {
    cy.run('plot_pointcloud_rgb')
      .get(win_selector)
      .should('have.length', 1);
    cy.get(win_selector)
      .first()
      .find('canvas')
      .should('have.length', 1);
    cy.get(win_selector)
      .first()
      .find('.bar')
      .contains('RGB cloud (');
  });
});
