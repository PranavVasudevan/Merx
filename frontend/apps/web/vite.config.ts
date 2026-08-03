import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // Three charting libraries now ship (recharts, lightweight-charts, echarts)
        // and the app has ~20 routes. Without this every one of them landed in a
        // single 1,015,105-byte chunk that every visitor downloaded regardless of
        // which page they opened. Splitting the heavy vendors out means a page that
        // uses only recharts never pays for echarts, and the vendor chunks stay
        // cached across app deploys.
        // Rolldown (Vite 8) takes the function form only — the object map that
        // rollup accepted is a type error here.
        //
        // Match on the full `node_modules/<pkg>` prefix, NOT a bare substring: the
        // string "recharts" CONTAINS "echarts", so a naive `id.includes('echarts')`
        // silently swept all of recharts into the echarts chunk and made every
        // recharts page download 384kB of ECharts it never uses. Verified in the
        // built output, not assumed.
        manualChunks(id: string) {
          const p = id.replace(/\\/g, '/');           // Windows ids use backslashes
          if (!p.includes('/node_modules/')) return undefined;
          const pkg = (m: string) => p.includes(`/node_modules/${m}`);
          if (pkg('echarts') || pkg('zrender')) return 'vendor-echarts';
          if (pkg('recharts') || pkg('victory-vendor') || pkg('d3-')) return 'vendor-recharts';
          if (pkg('lightweight-charts') || pkg('fancy-canvas')) return 'vendor-lightweight-charts';
          if (pkg('motion')) return 'vendor-motion';
          if (pkg('react-router') || pkg('react/') || pkg('react-dom')) return 'vendor-react';
          return undefined;
        },
      },
    },
  },
})
