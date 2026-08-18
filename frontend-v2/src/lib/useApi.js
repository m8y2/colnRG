import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api.js';

// Small data-fetching hook shared by every page: calls `fn`, tracks a
// ChartFrame-compatible status ('loading' | 'error' | 'ready'), and
// re-fetches whenever `fn`'s identity changes.
//
// `fn` must be referentially stable across renders that shouldn't
// re-fetch — wrap it in `useCallback(() => api.getThing(x), [x])` at the
// call site (a literal dependency array is required there; the eslint
// react-hooks rules enforce this and will not accept a variable in its
// place, which is why this hook does not take a separate `deps` array
// itself — that would just move a non-literal array one level down).
export function useApi(fn) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const generation = useRef(0);

  useEffect(() => {
    const gen = ++generation.current;
    // Deliberate: reset to 'loading' the moment the inputs change. The
    // alternative the lint rule prefers (keep showing the previous data
    // while the next request is in flight) would briefly render one
    // measurement's readings under another measurement's heading, which
    // on a water-quality site is worse than a flash of a loading state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, status: 'loading', error: null }));
    fn()
      .then((data) => {
        if (gen !== generation.current) return;
        setState({ status: 'ready', data, error: null });
      })
      .catch((error) => {
        if (gen !== generation.current) return;
        const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.';
        setState({ status: 'error', data: null, error: message });
      });
  }, [fn]);

  const reload = () => {
    generation.current += 1;
    const gen = generation.current;
    setState((s) => ({ ...s, status: 'loading', error: null }));
    fn()
      .then((data) => {
        if (gen !== generation.current) return;
        setState({ status: 'ready', data, error: null });
      })
      .catch((error) => {
        if (gen !== generation.current) return;
        const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.';
        setState({ status: 'error', data: null, error: message });
      });
  };

  return { ...state, reload };
}
