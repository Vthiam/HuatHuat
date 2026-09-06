import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // Only the GitHub Pages production build is served from a /HuatHuat/
  // subpath -- local dev (npm run dev / ./dev.sh) must stay at the root,
  // or the dev server would serve from http://localhost:5173/HuatHuat/
  // instead of http://localhost:5173/.
  base: mode === 'production' ? '/HuatHuat/' : '/',
  plugins: [react()],
  server: {
    open: true,
  },
}))
