import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies API calls to the FastAPI backend; in production the
// built app is served by FastAPI itself (see punchcard/backend/main.py).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/sessions': 'http://localhost:8000',
    },
  },
})
