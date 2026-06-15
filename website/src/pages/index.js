import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './index.module.css';

const features = [
  {
    icon: '\u{1F4C8}',
    title: 'Real-time Visualization',
    description:
      'Stream live data to interactive plots, images, and text. Monitor experiments as they run with instant visual feedback.',
  },
  {
    icon: '\u{1F3A8}',
    title: 'Rich Plot Types',
    description:
      'Scatter, line, bar, heatmap, histogram, surface, contour, mesh, and more. Powered by Plotly with full customization.',
  },
  {
    icon: '\u{1F465}',
    title: 'Collaborative Dashboards',
    description:
      'Share environments via URL. Organize visualizations into named environments with drag-and-drop window management.',
  },
];

function Hero() {
  const { siteConfig } = useDocusaurusContext();
  const logoUrl = useBaseUrl('/img/logo.png');
  const screenshotUrl = useBaseUrl('/img/demo-dashboard.png');

  return (
    <header className={styles.hero}>
      <div className={styles.heroInner}>
        <img
          src={logoUrl}
          alt="Visdom Logo"
          className={styles.heroLogo}
        />
        <h1 className={styles.heroTitle}>{siteConfig.title}</h1>
        <p className={styles.heroTagline}>{siteConfig.tagline}</p>
        <div className={styles.heroCtas}>
          <Link
            className={styles.ctaPrimary}
            to="/docs/getting-started/installation"
          >
            Get Started
          </Link>
          <Link
            className={styles.ctaSecondary}
            href="https://github.com/fossasia/visdom"
          >
            GitHub
          </Link>
        </div>
        <div className={styles.heroScreenshot}>
          <img
            src={screenshotUrl}
            alt="Visdom Dashboard"
            loading="lazy"
          />
        </div>
      </div>
    </header>
  );
}

function Features() {
  return (
    <section className={styles.features}>
      <div className={styles.featuresInner}>
        <h2 className={styles.featuresTitle}>
          Visualize your experiments
        </h2>
        <div className={styles.featuresGrid}>
          {features.map((feature, idx) => (
            <div key={idx} className={styles.featureCard}>
              <span className={styles.featureIcon}>{feature.icon}</span>
              <h3 className={styles.featureTitle}>{feature.title}</h3>
              <p className={styles.featureDesc}>{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function QuickStart() {
  return (
    <section className={styles.quickStart}>
      <h2 className={styles.quickStartTitle}>Up and running in seconds</h2>
      <div className={styles.quickStartCode}>
        <code>
          <span className={styles.prompt}>$ </span>
          <span className={styles.command}>pip install visdom</span>
        </code>
        <code>
          <span className={styles.prompt}>$ </span>
          <span className={styles.command}>visdom</span>
        </code>
      </div>
      <br />
      <Link className={styles.quickStartLink} to="/docs/getting-started/installation">
        Read the docs &rarr;
      </Link>
    </section>
  );
}

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.title}
      description={siteConfig.tagline}
    >
      <Hero />
      <Features />
      <QuickStart />
    </Layout>
  );
}
