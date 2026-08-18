import { useEffect, useState } from 'react';
import SkipLink from './components/SkipLink.jsx';
import PrimaryNav from './components/PrimaryNav.jsx';
import ThemeToggle from './components/ThemeToggle.jsx';
import RiverNow from './pages/RiverNow.jsx';
import YourPlace from './pages/YourPlace.jsx';
import OverTime from './pages/OverTime.jsx';
import AlongTheRiver from './pages/AlongTheRiver.jsx';
import Reports from './pages/Reports.jsx';
import WhatWeMeasure from './pages/WhatWeMeasure.jsx';
import AllData from './pages/AllData.jsx';

// Plain-language pages, in the order they should appear in the nav (see
// V2 spec "Information architecture"). Hash-based routing was chosen over
// a router library (none is in package.json) because it needs no server
// rewrite rules to support deep links once this is deployed under nginx
// alongside v1 and the not-yet-written /v2 nginx config.
const ROUTES = [
  { path: 'river-now', label: 'The river right now', Component: RiverNow },
  { path: 'your-place', label: 'Your place', Component: YourPlace },
  { path: 'over-time', label: 'Change over time', Component: OverTime },
  { path: 'along-the-river', label: 'Along the river', Component: AlongTheRiver },
  { path: 'reports', label: 'Reports', Component: Reports },
  { path: 'what-we-measure', label: 'What we measure', Component: WhatWeMeasure },
  { path: 'all-data', label: 'All the data', Component: AllData },
];

const DEFAULT_PATH = 'river-now';

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const [path, ...rest] = raw.split('/');
  return { path: path || DEFAULT_PATH, rest: rest.join('/') };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Move focus to the main region on navigation so keyboard and screen
  // reader users land somewhere sensible instead of at a stale position.
  useEffect(() => {
    const main = document.getElementById('main-content');
    main?.focus();
  }, [route.path]);

  const active = ROUTES.find((r) => r.path === route.path) || ROUTES[0];
  const Page = active.Component;

  return (
    <div className="app-shell">
      <SkipLink />
      <header className="site-header">
        <div className="container site-header__bar">
          <a className="site-header__brand" href="#/river-now">
            <span className="site-header__title">Coln River Guardians</span>
            <span className="site-header__subtitle">River health, explained in plain English</span>
          </a>
          <ThemeToggle />
        </div>
      </header>
      <PrimaryNav items={ROUTES} current={active.path} />
      <main id="main-content" className="site-main" tabIndex={-1}>
        <div className="container">
          <Page routeParam={route.rest} navigate={(path) => { window.location.hash = `#/${path}`; }} />
        </div>
      </main>
      <footer className="site-footer">
        <div className="container site-footer__row">
          <span>
            Water quality data collected by Coln River Guardians volunteers on the River Coln, Gloucestershire.
          </span>
          <span>Site codes are volunteers&rsquo; initials, not place names.</span>
        </div>
      </footer>
    </div>
  );
}
