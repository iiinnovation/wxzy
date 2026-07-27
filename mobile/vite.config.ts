import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { configDefaults, defineConfig } from 'vitest/config'

export default defineConfig(({ command, mode }) => {
  const environment = loadEnv(mode, process.cwd(), '')
  if (command === 'build' && !environment.VITE_API_BASE_URL?.trim()) {
    throw new Error('VITE_API_BASE_URL is required for production builds')
  }

  return {
    base: './',
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 4173
    },
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      setupFiles: './src/test/setup.ts'
    }
  }
})
