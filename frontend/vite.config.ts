import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the UI calls the FastAPI backend through this proxy, so no CORS is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
})
