import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 개발 중에는 프론트(5173)와 백엔드(8000)가 다른 포트에서 뜬다.
// /api 로 시작하는 요청을 백엔드로 넘겨 두면 브라우저 입장에서는 같은 주소라
// CORS 문제도, 배포할 때 주소를 바꿔야 할 일도 생기지 않는다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
