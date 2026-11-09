import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/smartface-attendance/',
  plugins: [react()],
})
