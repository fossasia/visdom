/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docsSidebar: [
    'intro',
    {
      type: 'category',
      label: 'User Guide',
      collapsed: false,
      link: {
        type: 'doc',
        id: 'user-guide/quick-start',
      },
      items: [
        'user-guide/creating-visualizations',
        'user-guide/environments',
        'user-guide/live-updates',
        'user-guide/windows-and-layouts',
        'user-guide/callbacks',
        'user-guide/sharing-and-security',
        'user-guide/pytorch-integration',
      ],
    },
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      link: {
        type: 'doc',
        id: 'getting-started/installation',
      },
      items: [
        'getting-started/usage',
        'getting-started/command-line-options',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      collapsed: false,
      link: {
        type: 'doc',
        id: 'concepts/windows',
      },
      items: [
        'concepts/environments',
        'concepts/callbacks',
        'concepts/views-and-filters',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      collapsed: false,
      link: {
        type: 'doc',
        id: 'api/overview',
      },
      items: [
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
