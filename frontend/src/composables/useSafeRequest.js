/**
 * 安全请求组合式函数
 * 组件卸载时自动取消所有未完成的请求，防止快速切换页面报错
 */
import { onBeforeUnmount, getCurrentInstance } from 'vue'
import request from '@/utils/request'

export function useSafeRequest() {
  const controllers = new Set()
  const timers = new Set()
  let isActive = false

  if (getCurrentInstance()) {
    isActive = true
    onBeforeUnmount(() => {
      isActive = false
      controllers.forEach(c => { try { c.abort() } catch {} })
      controllers.clear()
      timers.forEach(t => { clearTimeout(t); clearInterval(t) })
      timers.clear()
    })
  }

  const safeGet = async (url, params, opts = {}) => {
    if (!isActive) return
    const controller = new AbortController()
    controllers.add(controller)
    try {
      const data = await request.get(url, { params, signal: controller.signal, ...opts })
      return data
    } catch (e) {
      if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return
      throw e
    } finally {
      controllers.delete(controller)
    }
  }

  const safePost = async (url, body, opts = {}) => {
    if (!isActive) return
    const controller = new AbortController()
    controllers.add(controller)
    try {
      const data = await request.post(url, body, { signal: controller.signal, ...opts })
      return data
    } catch (e) {
      if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return
      throw e
    } finally {
      controllers.delete(controller)
    }
  }

  const safeSetInterval = (fn, delay) => {
    const id = setInterval(() => {
      if (!isActive) { clearInterval(id); return }
      try { fn() } catch (e) {
        if (e?.name !== 'CanceledError') console.warn('[safeInterval]', e)
      }
    }, delay)
    timers.add(id)
    return id
  }

  const safeSetTimeout = (fn, delay) => {
    const id = setTimeout(() => {
      if (!isActive) return
      timers.delete(id)
      try { fn() } catch {}
    }, delay)
    timers.add(id)
    return id
  }

  return {
    safeGet,
    safePost,
    safeSetInterval,
    safeSetTimeout,
    get isActive() { return isActive }
  }
}
