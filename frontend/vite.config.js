import { defineConfig } from 'vite'

export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  optimizeDeps: {
    exclude: [
      "d3-shape",
      "d3-array",
      "d3-scale",
      "d3-interpolate",
      "d3-color",
      "d3-format",
      "d3-time",
      "d3-ease",
      "d3-path",
      "d3-timer",
    ],
  },
})
