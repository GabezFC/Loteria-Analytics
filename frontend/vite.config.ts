/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

declare const process: { env: Record<string, string | undefined> };

// A 3000 é ocupada pelo Nginx do Docker; o dev server usa 5173.
const target = process.env.VITE_API_TARGET ?? 'http://192.168.0.121:3000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '192.168.0.121',
    port: 5173,
    // Apenas desenvolvimento local: encaminha /api ao backend (via Nginx por padrão).
    proxy: { '/api': target },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
