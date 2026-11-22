import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Kodo runs as a plain Vite dev server locally and as static files behind Nginx in Docker.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  envPrefix: ['VITE_'],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
