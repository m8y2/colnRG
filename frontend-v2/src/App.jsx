import { lazy, Suspense, useEffect, useState } from 'react';
import SkipLink from './components/SkipLink.jsx';
import PrimaryNav from './components/PrimaryNav.jsx';
import ThemeToggle from './components/ThemeToggle.jsx';
import { LoadingState } from './components/AsyncState.jsx';

// Lazy, one chunk per page: the bundle was one 793 kB file that every
// page paid for on first load, Recharts and Leaflet included, even to
// show the Reports page's static PDF. Route-based code splitting means a
// visitor only downloads the page they actually asked for; v1 already
// does this per-component (see frontend/src/App.jsx) -- this is the same
// idea applied per-route instead, which is the coarser, simpler version
// that fits this app's one-component-per-page structure.
const RiverNow = lazy(() => import('./pages/RiverNow.jsx'));
const YourPlace = lazy(() => import('./pages/YourPlace.jsx'));
const PhotoGallery = lazy(() => import('./pages/PhotoGallery.jsx'));
const OverTime = lazy(() => import('./pages/OverTime.jsx'));
const AlongTheRiver = lazy(() => import('./pages/AlongTheRiver.jsx'));
const Reports = lazy(() => import('./pages/Reports.jsx'));
const WhatWeMeasure = lazy(() => import('./pages/WhatWeMeasure.jsx'));
const AllData = lazy(() => import('./pages/AllData.jsx'));

// Plain-language pages, in the order they should appear in the nav (see
// V2 spec "Information architecture"). Hash-based routing was chosen over
// a router library (none is in package.json) because it needs no server
// rewrite rules to support deep links once this is deployed under nginx
// alongside v1 and the not-yet-written /v2 nginx config.
const ROUTES = [
  { path: 'river-now', label: 'The river right now', Component: RiverNow },
  { path: 'your-place', label: 'Your place', Component: YourPlace },
  { path: 'photos', label: 'Photo gallery', Component: PhotoGallery },
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
          </a>
          <ThemeToggle />
        </div>
      </header>
      <PrimaryNav items={ROUTES} current={active.path} />
      <main id="main-content" className="site-main" tabIndex={-1}>
        <div className="container">
          <Suspense fallback={<LoadingState label="Loading…" />}>
            <Page routeParam={route.rest} navigate={(path) => { window.location.hash = `#/${path}`; }} />
          </Suspense>
        </div>
      </main>
      <footer className="site-footer">
        <div className="container site-footer__row">
          <span>
            Water quality data collected by Coln River Guardians volunteers on the River Coln, Gloucestershire.
          </span>
          <span className="license-notice">
            This website&rsquo;s use is under the GPL v3 license.
          </span>
        </div>
      </footer>
    </div>
  );
}
