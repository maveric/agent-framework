import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: {
        port: 3000,
        // Proxy only in development mode
        // Uses environment variables with localhost as fallback
        proxy: {
            '/api': {
                target: process.env.VITE_API_URL || 'http://localhost:8085',
                changeOrigin: true,
            },
            '/ws': {
                target: (process.env.VITE_WS_URL || 'ws://localhost:8085').replace('ws://', 'http://'),
                ws: true,
            },
        },
    },
})
