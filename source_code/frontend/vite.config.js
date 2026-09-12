import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'node:path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())

  return {
    plugins: [
      vue(),
      // Element Plus 自动按需引入，无需手动import
      AutoImport({ resolvers: [// importStyle 用 'css'（预编译样式）而非 'sass'：
// 'sass' 会触发 EP 的 SCSS 源码逐组件编译（form-item.scss 等），
// EP 源码大量使用废弃 global built-in（lighten/darken），每次编译刷 deprecation，
// 叠加 additionalData 注入 override.scss 形成 N 倍编译量，vite 易资源耗尽崩溃。
// main.js 已全量引入 element-plus/dist/index.css 预编译样式，按需引入预编译 CSS 即可，零 SCSS 编译。
ElementPlusResolver({ importStyle: 'css' })] }),
      Components({ resolvers: [// importStyle 用 'css'（预编译样式）而非 'sass'：
// 'sass' 会触发 EP 的 SCSS 源码逐组件编译（form-item.scss 等），
// EP 源码大量使用废弃 global built-in（lighten/darken），每次编译刷 deprecation，
// 叠加 additionalData 注入 override.scss 形成 N 倍编译量，vite 易资源耗尽崩溃。
// main.js 已全量引入 element-plus/dist/index.css 预编译样式，按需引入预编译 CSS 即可，零 SCSS 编译。
ElementPlusResolver({ importStyle: 'css' })] }),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    css: {
      preprocessorOptions: {
        scss: {
          // 覆盖 Element Plus 变量 → 护眼深色主题
          additionalData: `
            @use "@/styles/element-plus-override.scss" as *;
          `,
        },
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      // 开发代理：后端跑在 8000。
      // 注意：target 必须是完整后端 URL，不能用前端 baseURL(VITE_API_BASE='/')
      // —— 二者语义不同：VITE_API_BASE 给 axios 用(相对路径走代理)，proxy target 给 vite 用(转发目标)
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        // /docs /health 等也代理过去，方便开发时直接 5173/docs 看 Swagger
        '/docs': { target: 'http://127.0.0.1:8000', changeOrigin: true },
        '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
        '/openapi.json': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
      minify: 'esbuild',
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          // 代码分包，首屏更快
          manualChunks: {
            vue: ['vue', 'vue-router', 'pinia'],
            element: ['element-plus', '@element-plus/icons-vue'],
            charts: ['echarts', 'vue-echarts'],
            utils: ['axios', 'dayjs'],
          },
        },
      },
    },
  }
})
