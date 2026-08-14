import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Separate from vite.config.ts, not a merged `test` block in it — that file's
// build.rolldownOptions (manualChunks etc.) are bundler-output concerns vitest
// never touches, and `vitest/config`'s defineConfig (not `vite`'s) is what
// types the `test` key at all.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/testSetup.ts'],
    css: false,
  },
})
