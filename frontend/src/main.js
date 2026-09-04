/* =========================================================
   开发期全局错误捕获 & 全屏显示（无需开 F12）
   —— 应对"黑屏/白屏"时控制台不可达的情况。
   生产可删除此段。
   ========================================================= */
(() => {
  const showError = (title, lines) => {
    const id = '__APP_FATAL_OVERLAY__'
    if (document.getElementById(id)) return
    const box = document.createElement('div')
    box.id = id
    box.style.cssText = `
      position:fixed; inset:0; z-index:99999;
      background:#1a0b0b; color:#ffb4b4;
      font-family:Consolas,Menlo,monospace; font-size:13px; line-height:1.55;
      padding: 16px 22px; overflow:auto; white-space:pre-wrap; word-break:break-all;
      border-top: 4px solid #F87171;
    `
    const h = document.createElement('div')
    h.style.cssText = 'font-size:18px;font-weight:700;color:#F87171;margin-bottom:10px;'
    h.textContent = '❌ ' + title
    const b = document.createElement('div')
    b.textContent = lines.map(l => String(l)).join('\n')
    box.appendChild(h); box.appendChild(b)
    // 若 #app 是空壳，把错误直接挂到 body 即可，body 存在即挂
    const target = document.body || document.documentElement
    target.appendChild(box)
    console.error('[' + title + ']', lines)
  }
  const isHarmlessError = (err) => {
    if (!err) return false
    const msg = err.message || String(err)
    // 组件卸载后异步更新: Vue 内部警告
    if (msg.includes('unmounted') || msg.includes('Unmounted')) return true
    // 请求被取消: AbortController / axios cancel
    if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return true
    if (msg.includes('cancel') || msg.includes('abort')) return true
    // 路由切换时组件仍在校验/渲染
    if (msg.includes('navigation') || msg.includes('NavigationFailure')) return true
    // ECharts dispose 后仍触发 resize
    if (msg.includes('dispose') || msg.includes('echarts')) return true
    // ResizeObserver loop: ECharts/Element Plus 布局变化时的无害警告
    if (msg.includes('ResizeObserver')) return true
    // "Cannot read properties of undefined" 常见于快速切换时数据未就绪
    if (msg.includes("Cannot read properties of undefined")) return true
    if (msg.includes("Cannot read property") || msg.includes("reading '0'") || msg.includes("reading 'length'")) return true
    return false
  }

  window.addEventListener('error', (e) => {
    if (e.message === 'Script error.' && !e.error && e.lineno === 0 && e.colno === 0) {
      console.warn('[ignored] Script error (cross-origin / CORS-opaque error, likely harmless)')
      return
    }
    if (e.error && isHarmlessError(e.error)) {
      console.warn('[ignored] Harmless error during page transition:', e.message)
      return
    }
    if (!e.error && !e.message && e.target && e.target !== window && e.target.tagName) {
      const tag = e.target.tagName
      const src = e.target.src || e.target.href || ''
      console.warn('[ignored] Resource loading error:', tag, src)
      return
    }
    const msg = e.error && e.error.stack ? String(e.error.stack) : `${e.message} (${e.filename}:${e.lineno}:${e.colno})`
    showError('JS 运行时错误', [msg, 'URL: ' + location.href])
  }, true)
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason
    if (isHarmlessError(r)) {
      console.warn('[ignored] Harmless promise rejection during page transition:', r)
      return
    }
    const msg = r && r.stack ? String(r.stack) : String(r)
    showError('未捕获 Promise 拒绝', [msg, 'URL: ' + location.href])
  })
  window.addEventListener('vite:preloadError', (e) => {
    console.warn('[vite:preloadError] Stale chunk detected, reloading page...')
    e.preventDefault()
    if (!window.__viteReloading) {
      window.__viteReloading = true
      window.location.reload()
    }
  })
  // 旧版 vite：捕获 module load fail 最后兜底
  window.addEventListener('load', () => {
    setTimeout(() => {
      if (!document.querySelector('#app > *:not(#__APP_FATAL_OVERLAY__)')) {
        showError('#app 挂载为空（Vue 未渲染任何子节点）', [
          '可能是 main.js / App.vue / 路由组件抛出错误或路由未命中。',
          '请查看上方红色错误框；若无，则在 DevTools Console 看 SyntaxError/模块加载失败。',
          '当前路由: ' + location.href,
          'has router-view in DOM: ' + !!document.querySelector('router-view'),
        ])
      }
    }, 3500)
  })
})()

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPersist from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
// 顺序：先基础组件样式，再暗色变量覆盖，最后全局/页面样式
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import App from './App.vue'
import router from './router'
import './styles/global.scss'

// ---------- 初始化 ----------
// 启用 Element Plus 暗色模式：dark/css-vars.css 依赖 :root.dark 选择器
// 项目为护眼深色主题，必须挂载前给 <html> 加 .dark，否则 EP 组件（按钮/输入框/下拉等）
// 会用亮色默认变量，在深色背景上显示白底，视觉割裂
document.documentElement.classList.add('dark')

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPersist)

// ---------- 全局注册 Element Plus 图标 ----------
for (const [key, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, comp)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn, size: 'default' })

// Vue 应用级错误处理器：捕获组件内部错误（快速切换页面时常见）
app.config.errorHandler = (err, instance, info) => {
  const msg = err?.message || String(err)
  // 过滤快速切换页面时的无害错误
  if (msg.includes('unmounted') || msg.includes('Unmounted') ||
      msg.includes('cancel') || msg.includes('abort') ||
      err.name === 'CanceledError' || err.code === 'ERR_CANCELED' ||
      msg.includes("Cannot read properties of undefined") ||
      msg.includes("Cannot read property") ||
      msg.includes('dispose') || msg.includes('echarts') ||
      msg.includes('ResizeObserver')) {
    console.warn('[Vue errorHandler] Ignored harmless error:', msg, info)
    return
  }
  console.error('[Vue errorHandler]', err, info)
}

try {
  app.mount('#app')
  // 开发期暴露，辅助排查（按经验 1322011 的 failure 经验：避免 router 全局不可达导致诊断链断）
  if (import.meta.env.DEV) {
    window.__APP_ROUTER__ = router
    window.__APP_PINIA__ = pinia
  }
} catch (e) {
  // 挂载阶段同步抛错 → 显示错误
  document.documentElement.classList.add('dark') // 至少把暗色背景设上
  ;(function (err){
    const id = '__APP_FATAL_OVERLAY__'
    const box = document.createElement('div')
    box.id = id
    box.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#1a0b0b;color:#ffb4b4;font-family:Consolas,Menlo,monospace;font-size:13px;line-height:1.55;padding:16px 22px;overflow:auto;border-top:4px solid #F87171;'
    const h = document.createElement('div')
    h.style.cssText = 'font-size:18px;font-weight:700;color:#F87171;margin-bottom:10px;'
    h.textContent = '❌ Vue 挂载阶段抛出错误'
    const b = document.createElement('div')
    b.style.whiteSpace = 'pre-wrap'
    b.textContent = (err && err.stack ? err.stack : String(err)) + '\n\nURL: ' + location.href
    box.appendChild(h); box.appendChild(b)
    ;(document.body || document.documentElement).appendChild(box)
  })(e)
  throw e
}
