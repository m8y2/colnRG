import { defineConfig } from 'vite'

// DEMO_BUILD=1 npm run build produces the single-file bundle
// scripts/build-demo.py needs: every page is React.lazy() now (see
// App.jsx), so the normal build is one small chunk per route, and
// build-demo.py can only inline one JS file into its one-file HTML --
// the rest would 404 with no server behind them. inlineDynamicImports
// folds every lazy chunk back into the entry file for this build only;
// the real deployed site keeps the split build, which is what actually
// wants the smaller initial download.
const demoBuild = process.env.DEMO_BUILD === '1'

export default defineConfig({
  base: '/',
  esbuild: { jsx: 'automatic' },
  server: {
    port: 5174,
    host: '0.0.0.0',
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // `vite preview` does not inherit `server.proxy`. It needs its own, or
  // the built app has no backend -- and checking the built app is the
  // point: v1's missing bar charts only appear in a production build.
  preview: {
    port: 5175,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // Pre-bundling breaks these (see Dashboard/AGENTS.md "Vite quirks")
  optimizeDeps: {
    exclude: [
      'd3-shape', 'd3-array', 'd3-scale', 'd3-interpolate', 'd3-color',
      'd3-format', 'd3-time', 'd3-ease', 'd3-path', 'd3-timer',
      'victory-vendor',
    ],
  },
  build: demoBuild ? { rollupOptions: { output: { inlineDynamicImports: true } } } : {},
})
