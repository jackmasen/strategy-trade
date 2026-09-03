import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { isDev } from '@/utils/env'

export { API_PREFIX } from '@/utils/env'

let _isLoggingOut = false

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
})

request.interceptors.request.use(
  (config) => {
    const user = useUserStore()
    if (user.token) {
      config.headers.Authorization = `Bearer ${user.token}`
    }
    // FormData: let browser set Content-Type with correct multipart boundary
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }
    if (isDev()) {
      console.log(`[REQ] ${config.method?.toUpperCase()} ${config.url}`, config.params || config.data)
    }
    return config
  },
  (err) => Promise.reject(err)
)

request.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      if (body.code === 4010 || body.code === 401) {
        if (!_isLoggingOut) {
          _isLoggingOut = true
          const user = useUserStore()
          user.logout()
          ElMessage.warning('登录已过期，请重新登录')
          setTimeout(() => { _isLoggingOut = false }, 2000)
        }
      } else {
        ElMessage({
          showClose: true,
          message: body.message || '请求失败',
          type: body.code >= 5000 ? 'error' : (body.code >= 4500 ? 'warning' : 'error'),
          duration: 3200,
        })
      }
      return Promise.reject(new Error(body.message || `Error code ${body.code}`))
    }
    return body
  },
  (err) => {
    const status = err.response?.status
    const silent = err.config?._silent
    if (silent) {
      return Promise.reject(err)
    }
    if (status === 401) {
      if (!_isLoggingOut) {
        _isLoggingOut = true
        const user = useUserStore()
        user.logout()
        ElMessage.warning('登录已过期，请重新登录')
        setTimeout(() => { _isLoggingOut = false }, 2000)
      }
      return Promise.reject(err)
    }
    let msg = err.message || '网络异常'
    if (status === 403) {
      msg = '权限不足'
    } else if (status === 404) {
      msg = '接口不存在'
    } else if (status === 422) {
      msg = '参数校验失败'
    } else if (status >= 500) {
      msg = '服务器错误，请稍后重试'
    } else if (!window.navigator.onLine) {
      msg = '网络已断开，请检查网络'
    }
    ElMessage({ showClose: true, message: msg, type: 'error', duration: 4000 })
    return Promise.reject(err)
  }
)

export const http = {
  get: (url, params, opts = {}) => request.get(url, { params, ...opts }),
  post: (url, data, config) => request.post(url, data, config),
  put: (url, data) => request.put(url, data),
  patch: (url, data) => request.patch(url, data),
  delete: (url, params) => request.delete(url, { params }),
  upload: (url, file, extra = {}, filename = 'file') => {
    const fd = new FormData()
    fd.append(filename, file)
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v))
    return request.post(url, fd)
  },
  download: (url, params, filename) =>
    request.get(url, { params, responseType: 'blob' }).then((blob) => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename || 'download'
      link.click()
      URL.revokeObjectURL(link.href)
    }),
}

export default request
