/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { handleMockRequest } from './src/mock/handler'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const useMock = (process.env.VITE_USE_MOCK ?? env.VITE_USE_MOCK) === 'true'
  return {
    plugins: [
      react(),
      tailwindcss(),
      {
        name: 'hologram-local-mock',
        configureServer(server) {
          if (!useMock) return
          server.middlewares.use(async (req, res, next) => {
            if (!req.url?.startsWith('/api/')) return next()
            try {
              const chunks: Buffer[] = []
              for await (const chunk of req) chunks.push(Buffer.from(chunk))
              const body = Buffer.concat(chunks).toString()
              const response = await handleMockRequest(new Request(new URL(req.url, 'http://localhost'), {
                method: req.method,
                headers: { 'Content-Type': 'application/json' },
                ...(body ? { body } : {}),
              }))
              if (!response) return next()
              res.statusCode = response.status
              response.headers.forEach((value, key) => res.setHeader(key, value))
              res.end(await response.text())
            } catch {
              res.statusCode = 400
              res.end('Invalid mock request')
            }
          })
        },
      },
    ],
    server: {
      proxy: {
        '/api': { target: process.env.API_PROXY_TARGET ?? 'http://localhost:8000', changeOrigin: true },
        '/ws': { target: 'http://localhost:8000', ws: true },
      },
    },
    test: { include: ['src/**/*.test.ts', 'src/**/*.test.tsx'], environment: 'node' },
  }
})
