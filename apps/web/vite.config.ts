import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Kodo runs as a plain Vite app in the browser and inside Tauri (devUrl http://localhost:5173).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
