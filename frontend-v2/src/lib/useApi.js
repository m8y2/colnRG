import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api.js';

// Small data-fetching hook shared by every page: calls `fn`, tracks a
// ChartFrame-compatible status ('loading' | 'error' | 'ready'), and
// re-fetches when `deps` change.
//
// `fn` is held in a ref and deliberately NOT a dependency of the effect.
// Every call site passes an inline arrow (`useApi(() => api.getX(y), [y])`),
// which is a new function on every render — depending on its identity
// meant: effect runs -> setState -> re-render -> new `fn` -> effect runs
// again, forever. In practice the browser fired the same request until it
// gave up with ERR_INSUFFICIENT_RESOURCES, React never settled, and no
// chart ever mounted. It looked exactly like v1's "axes but no bars" bug
// and had nothing to do with the charting library.
//
// So: `deps` is the re-fetch trigger, matching what the call sites were
// already passing as a second argument before this hook honoured it.
export function useApi(fn, deps = []) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const generation = useRef(0);
  const fnRef = useRef(fn);

  // Keep the latest closure without making it a re-fetch trigger, so a
  // reload() fired later still sees current props. Assigned in an effect
  // rather than during render: writing a ref while rendering is what the
  // react-hooks rules warn about, and this runs after every render anyway.
  useEffect(() => {
    fnRef.current = fn;
  });

  const run = (gen) => {
    fnRef
      .current()
      .then((data) => {
        if (gen !== generation.current) return;
        setState({ status: 'ready', data, error: null });
      })
      .catch((error) => {
        if (gen !== generation.current) return;
        const message =
          error instanceof ApiError
            ? error.message
            : 'Something went wrong. Please try again.';
        setState({ status: 'error', data: null, error: message });
      });
  };

  useEffect(() => {
    const gen = ++generation.current;
    // Reset to 'loading' the moment the inputs change. Keeping the previous
    // data on screen while the next request is in flight would briefly
    // render one measurement's readings under another measurement's
    // heading, which on a water-quality site is worse than a flash of a
    // loading state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, status: 'loading', error: null }));
    run(gen);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reload = () => {
    const gen = ++generation.current;
    setState((s) => ({ ...s, status: 'loading', error: null }));
    run(gen);
  };

  return { ...state, reload };
}
