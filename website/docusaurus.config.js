const { themes } = require('prism-react-renderer');

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Visdom',
  tagline:
    'Creating, organizing & sharing visualizations of live, rich data',
  favicon: 'img/favicon.ico',

  url: 'https://fossasia.github.io',
  baseUrl: '/visdom/',

  organizationName: 'fossasia',
  projectName: 'visdom',
  trailingSlash: false,

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  headTags: [
    {
      tagName: 'meta',
      attributes: {
        'http-equiv': 'Content-Security-Policy',
        content:
          "default-src 'self'; img-src 'self' https://user-images.githubusercontent.com https://img.shields.io data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'self' blob:; worker-src 'self' blob:;",
      },
    },
  ],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  themes: [
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        language: ['en'],
        indexDocs: true,
        indexBlog: false,
        docsRouteBasePath: '/',
      },
    ],
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl:
            'https://github.com/fossasia/visdom/tree/master/website/',
        },
        blog: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/logo.png',
      navbar: {
        title: 'Visdom',
        logo: {
          alt: 'Visdom',
          src: 'img/logo.png',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/api/overview',
            label: 'API',
            position: 'left',
          },
          {
            href: 'https://github.com/fossasia/visdom',
            label: 'GitHub',
            position: 'right',
          },
          {
            href: 'https://pypi.org/project/visdom',
            label: 'PyPI',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Documentation',
            items: [
              {
                label: 'Getting Started',
                to: '/getting-started/installation',
              },
              {
                label: 'API Reference',
                to: '/api/overview',
              },
              {
                label: 'Concepts',
                to: '/concepts/windows',
              },
            ],
          },
          {
            title: 'Community',
            items: [
              {
                label: 'GitHub Issues',
                href: 'https://github.com/fossasia/visdom/issues',
              },
              {
                label: 'Contributing',
                to: '/contributing',
              },
              {
                label: 'FOSSASIA',
                href: 'https://fossasia.org',
              },
            ],
          },
          {
            title: 'More',
            items: [
              {
                label: 'GitHub',
                href: 'https://github.com/fossasia/visdom',
              },
              {
                label: 'PyPI',
                href: 'https://pypi.org/project/visdom',
              },
              {
                label: 'License',
                href: 'https://github.com/fossasia/visdom/blob/master/LICENSE',
              },
            ],
          },
        ],
        copyright: `Copyright \u00a9 ${new Date().getFullYear()} FOSSASIA. Apache 2.0 Licensed.`,
      },
      prism: {
        theme: themes.github,
        darkTheme: themes.dracula,
        additionalLanguages: ['python', 'bash'],
      },
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },
    }),
};

module.exports = config;
