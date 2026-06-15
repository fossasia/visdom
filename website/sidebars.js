/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docsSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: [
        'getting-started/installation',
        'getting-started/usage',
        'getting-started/command-line-options',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/windows',
        'concepts/environments',
        'concepts/callbacks',
        'concepts/views-and-filters',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      collapsed: false,
      items: [
        'api/overview',
        'api/basics',
        'api/plotting',
        'api/generic-plots',
        'api/customizing-plots',
        'api/network-graph',
        'api/other-functions',
      ],
    },
    'contributing',
  ],
};

module.exports = sidebars;
