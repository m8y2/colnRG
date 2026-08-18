import { defineConfig } from 'vite'

export default defineConfig({
  base: '/v2/',
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
})
