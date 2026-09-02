import { defineStore } from 'pinia'
import { http, API_PREFIX } from '@/utils/request'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: '',
    refreshToken: '',
    userInfo: null, // { id, username, nickname, role, email, avatar, two_factor_enabled }
    menus: [],
  }),

  getters: {
    isLoggedIn: (s) => !!s.token && !!s.userInfo,
    isAdmin: (s) => s.userInfo?.role === 1,
    displayName: (s) => s.userInfo?.nickname || s.userInfo?.username || '未登录',
  },

  actions: {
    /**
     * 登录
     * @param {{username: string, password: string}} payload
     */
    async login(payload) {
      const resp = await http.post(`${API_PREFIX}/auth/login`, payload)
      this.token = resp.access_token
      this.refreshToken = resp.refresh_token
      // 优先用登录返回的 user（需后端返回完整字段），若后端返回不完整
      // （比如老版本只含 id/created_at/updated_at），立即调 /users/me 补全，
      // 否则 isAdmin/displayName 依赖的 role/nickname 会 undefined，
      // 导致用户管理菜单隐藏、顶栏用户信息空等运营阻塞 bug
      this.userInfo = resp.user
      if (!this.userInfo || this.userInfo.role == null || !this.userInfo.username) {
        try { await this.fetchMe() } catch (_) {}
      }
      await this.fetchMenus()
      return resp
    },

    /** 登出 */
    logout() {
      this.token = ''
      this.refreshToken = ''
      this.userInfo = null
      this.menus = []
      if (location.hash !== '#/login') {
        location.hash = '#/login'
      }
    },

    /** 尝试从 localStorage 恢复登录态 */
    tryRestoreLogin() {
      // 由 pinia-plugin-persistedstate 自动恢复
    },

    /** 获取菜单 */
    async fetchMenus() {
      try {
        this.menus = (await http.get(`${API_PREFIX}/me/menu`))?.menus || []
      } catch (e) {}
    },

    /** 修改自己的基础资料（昵称/邮箱/手机） */
    async updateProfile(payload) {
      const data = await http.put(`${API_PREFIX}/users/me`, payload || {})
      if (data && typeof data === 'object') {
        this.userInfo = { ...(this.userInfo || {}), ...data }
      }
      return data
    },

    /** 修改密码 */
    async changePassword(old_password, new_password) {
      return http.put(`${API_PREFIX}/users/me/password`, { old_password, new_password })
    },

    /** 获取当前用户信息 */
    async fetchMe() {
      this.userInfo = await http.get(`${API_PREFIX}/users/me`)
      return this.userInfo
    },
  },

  persist: {
    key: 'trading:user',
    storage: localStorage,
    paths: ['token', 'refreshToken', 'userInfo'],
  },
})
