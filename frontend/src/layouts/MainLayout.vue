<template>
  <div class="main-layout">
    <!-- 左侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: collapse }">
      <div class="logo">
        <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
          <rect width="32" height="32" rx="7" fill="#0F1A24" stroke="#25D07D" stroke-width="1.5"/>
          <path d="M6 22 L12 14 L16 18 L22 10 L28 16" stroke="#25D07D" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span v-if="!collapse" class="logo-text">策略交易系统</span>
      </div>
      <el-scrollbar class="sidebar-scroll">
        <el-menu
          :default-active="$route.path"
          :collapse="collapse"
          :collapse-transition="false"
          unique-opened
          router
          background-color="#0C151D"
          text-color="#97A6B6"
          active-text-color="#FFFFFF"
        >
          <template v-for="m in menuList" :key="m.path">
            <el-menu-item :index="m.path" v-if="!m.adminOnly || user.isAdmin">
              <el-icon><component :is="m.icon" /></el-icon>
              <template #title>
                <span>{{ m.title }}</span>
                <el-tag size="small" v-if="m.badge" :type="m.badgeType" effect="dark" style="margin-left:6px;">
                  {{ m.badge }}
                </el-tag>
              </template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
      <div class="sidebar-footer" v-if="!collapse">
        <div class="version">v1.0.0 · 护眼主题</div>
      </div>
    </aside>

    <!-- 右侧主体 -->
    <div class="main">
      <!-- 顶部栏 -->
      <header class="header">
        <div class="header-left">
          <el-button :icon="collapse ? Expand : Fold" circle text @click="collapse = !collapse" />
          <el-breadcrumb separator="/" class="bread">
            <el-breadcrumb-item>{{ $route.meta?.title || '首页' }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <!-- 实时时钟 -->
          <div class="clock monospace" :title="nowFull">
            <el-icon style="color:#97A6B6"><Timer /></el-icon>
            <span>{{ nowTime }}</span>
          </div>
          <!-- 风险等级 -->
          <div class="risk-tag" :title="'当前风险等级: 2 - 中低'">
            <span class="risk-dot r2"></span>
            风险 中低
          </div>
          <!-- 搜索 -->
          <el-input placeholder="搜索订单/策略/品种..." :prefix-icon="Search" size="default" class="search" clearable />
          <!-- 通知 -->
          <el-badge :value="unreadCount" :hidden="unreadCount === 0" class="notify" :max="99">
            <el-button :icon="Bell" circle text @click="showNotifications = true" />
          </el-badge>
          <!-- 全屏 -->
          <el-button :icon="FullScreen" circle text @click="toggleFullscreen" />
          <!-- 用户 -->
          <el-dropdown @command="onCommand">
            <div class="user-chip">
              <el-avatar :size="32" style="background:#1A382A;color:#25D07D;">
                {{ user.displayName?.charAt(0)?.toUpperCase() || 'A' }}
              </el-avatar>
              <div class="user-info">
                <div class="user-name">{{ user.displayName }}</div>
                <div class="user-role">
                  <el-tag size="small" :type="roleType" effect="dark">{{ roleName }}</el-tag>
                </div>
              </div>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile"><el-icon><User /></el-icon>个人中心</el-dropdown-item>
                <el-dropdown-item command="pwd"><el-icon><Lock /></el-icon>修改密码</el-dropdown-item>
                <el-dropdown-item divided command="logout"><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 内容 -->
      <main class="content">
        <router-view v-slot="{ Component, route }">
          <component :is="Component" :key="route.fullPath" />
        </router-view>
      </main>
    </div>

    <!-- 通知抽屉 -->
    <el-drawer v-model="showNotifications" title="通知中心" direction="rtl" size="420px" @open="loadNotifications">
      <template #header>
        <div style="display:flex;align-items:center;gap:8px;">
          <el-icon><Bell /></el-icon>
          <span>通知中心</span>
          <el-badge :value="unreadCount" :hidden="unreadCount===0" :max="99" style="margin-left:8px;" />
        </div>
      </template>
      <div v-loading="loadingNotif" style="min-height:200px;">
        <div v-if="notifications.length === 0 && !loadingNotif" style="text-align:center;padding:60px 0;color:#909399;">
          <el-icon :size="40" color="#3a4a5a"><Bell /></el-icon>
          <div style="margin-top:12px;">暂无通知</div>
        </div>
        <div v-for="n in notifications" :key="n.id" class="notif-item" :class="n.severity">
          <div class="notif-header">
            <el-tag :type="notifTagType(n.severity)" size="small" effect="dark">
              {{ notifTypeLabel(n.type) }}
            </el-tag>
            <span class="notif-time">{{ fmtTime(n.created_at) }}</span>
          </div>
          <div class="notif-title">{{ n.title }}</div>
          <div v-if="n.detail" class="notif-detail">{{ n.detail }}</div>
        </div>
        <div v-if="notifications.length > 0" style="text-align:center;padding:16px;">
          <el-button text @click="loadNotifications">刷新</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, onErrorCaptured } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Fold, Expand, Search, Bell, FullScreen, Timer, ArrowDown, User, Lock, SwitchButton,
  Monitor, Wallet, DataAnalysis, DataLine, TrendCharts, PieChart, Reading, Cpu, Histogram,
  Warning, Document, Setting, MagicStick
} from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import router from '@/router'
import { http, API_PREFIX } from '@/utils/request'

// 捕获子组件错误（快速切换页面时常见），防止全屏报错
onErrorCaptured((err, instance, info) => {
  const msg = err?.message || String(err)
  if (msg.includes('unmounted') || msg.includes('cancel') || msg.includes('abort') ||
      err.name === 'CanceledError' || err.code === 'ERR_CANCELED' ||
      msg.includes("Cannot read properties of undefined") ||
      msg.includes("Cannot read property") ||
      msg.includes('dispose') || msg.includes('echarts') ||
      msg.includes('ResizeObserver')) {
    console.warn('[MainLayout] Ignored child component error:', msg)
    return false // 阻止错误向上传播
  }
})

const user = useUserStore()
const r = useRouter()
const collapse = ref(false)

const roleName = computed(() => ({ 1: '超级管理员', 2: '运营', 3: '访客' })[user.userInfo?.role] || '用户')
const roleType = computed(() => ({ 1: 'success', 2: 'warning', 3: 'info' })[user.userInfo?.role] || 'info')

// 菜单（与路由对应，可从后端覆盖）
const menuList = computed(() => [
  { path: '/dashboard', title: '数据大屏',   icon: 'Monitor' },
  { path: '/exchange',  title: '交易所子账号', icon: 'Wallet' },
  { path: '/strategy',  title: '策略管理',   icon: 'DataAnalysis' },
  { path: '/kline',     title: 'K线行情',   icon: 'DataLine' },
  { path: '/trade',     title: '交易订单',   icon: 'TrendCharts' },
  { path: '/positions', title: '当前持仓',   icon: 'PieChart' },
  { path: '/news',      title: '新闻情绪',   icon: 'Reading' },
  { path: '/ai',        title: 'AI实时分析', icon: 'Cpu' },
  { path: '/quant-signal', title: '量化信号引擎', icon: 'TrendCharts' },
  { path: '/evolution',  title: '策略自我进化', icon: 'MagicStick' },
  { path: '/backtest',  title: '历史回测',   icon: 'Histogram' },
  { path: '/risk',      title: '风控中心',   icon: 'Warning' },
  { path: '/reports',   title: '财务报表',   icon: 'Document' },
  { path: '/crawler-health', title: '爬虫监控', icon: 'Monitor' },
  { path: '/users',     title: '用户管理',   icon: 'User', adminOnly: true },
  { path: '/settings',  title: '系统设置',   icon: 'Setting', adminOnly: true },
  { path: '/monitor',   title: '系统监控',   icon: 'Monitor', adminOnly: true },
  { path: '/system',    title: '系统管理',   icon: 'Monitor', adminOnly: true },
])

// 实时时钟
const nowTime = ref('')
const nowFull = ref('')
let timer
const updateClock = () => {
  const d = new Date()
  nowFull.value = d.toLocaleString('zh-CN')
  const pad = (n) => String(n).padStart(2, '0')
  nowTime.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
onMounted(() => {
  updateClock(); timer = setInterval(updateClock, 1000)
  loadUnreadCount()
  notifTimer = setInterval(loadUnreadCount, 60000)
})
onBeforeUnmount(() => { clearInterval(timer); clearInterval(notifTimer) })

// 通知中心
const showNotifications = ref(false)
const notifications = ref([])
const loadingNotif = ref(false)
const unreadCount = ref(0)
let notifTimer = null

const loadUnreadCount = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/notifications/unread-count`)
    unreadCount.value = r.count || 0
  } catch {}
}

const loadNotifications = async () => {
  loadingNotif.value = true
  try {
    const r = await http.get(`${API_PREFIX}/notifications`, { limit: 30 })
    notifications.value = r.items || []
    unreadCount.value = r.unread || 0
  } catch {} finally {
    loadingNotif.value = false
  }
}

const notifTagType = (sev) => ({
  info: 'info', warning: 'warning', danger: 'danger', success: 'success'
})[sev] || 'info'

const notifTypeLabel = (t) => ({
  risk: '风控', ai: 'AI分析', backtest: '回测', trade: '交易'
})[t] || '通知'

const fmtTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString().slice(0, 5)
}

// 全屏
const toggleFullscreen = () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.()
  else document.exitFullscreen?.()
}

// 用户操作
const onCommand = async (c) => {
  if (c === 'profile') r.push('/profile')
  else if (c === 'pwd') {
    const { value } = await ElMessageBox.prompt('请输入原密码', '修改密码', {
      inputType: 'password',
      confirmButtonText: '下一步',
    })
    const { value: np } = await ElMessageBox.prompt('请输入新密码(>=6位)', '修改密码', {
      inputType: 'password',
      inputValidator: (v) => v?.length >= 6 || '新密码至少6位',
    })
    await user.changePassword(value, np)
    ElMessage.success('密码修改成功')
  } else if (c === 'logout') {
    await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })
    user.logout()
  }
}
</script>

<style lang="scss" scoped>
.main-layout {
  height: 100vh;
  width: 100vw;
  display: flex;
  background: #0F1A24;
  color: #D8E2EC;
  overflow: hidden;
}

/* ----- Sidebar ----- */
.sidebar {
  width: 240px;
  min-width: 240px;
  background: #0C151D;
  border-right: 1px solid #192738;
  display: flex;
  flex-direction: column;
  transition: width .2s ease;
  &.collapsed {
    width: 64px;
    min-width: 64px;
  }
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid #192738;
  .logo-text {
    font-size: 16px;
    font-weight: 700;
    color: #F0F4F8;
    letter-spacing: .5px;
    white-space: nowrap;
  }
}
.sidebar-scroll {
  flex: 1;
  :deep(.el-menu) {
    border-right: none;
    padding: 8px 0;
  }
  :deep(.el-menu-item) {
    height: 46px;
    line-height: 46px;
    margin: 2px 10px;
    border-radius: 8px;
    &:hover {
      background: #152330 !important;
      color: #FFFFFF !important;
    }
    &.is-active {
      background: linear-gradient(90deg, #1A382A 0%, #152330 100%) !important;
      color: #FFFFFF !important;
      border-left: 3px solid #25D07D;
      .el-icon { color: #25D07D !important; }
    }
  }
}
.sidebar-footer {
  padding: 10px 16px;
  border-top: 1px solid #192738;
  .version {
    font-size: 11px;
    color: #4E5F73;
    text-align: center;
  }
}

/* ----- Main ----- */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.header {
  height: 60px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(18, 30, 43, 0.85);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid #192738;
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.bread :deep(.el-breadcrumb__inner) {
  color: #97A6B6;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.clock {
  background: #152330;
  border: 1px solid #1E2E41;
  border-radius: 8px;
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #D8E2EC;
  font-size: 13px;
  letter-spacing: 1px;
}
.risk-tag {
  background: #152330;
  border: 1px solid #1E2E41;
  border-radius: 20px;
  padding: 5px 14px;
  font-size: 12px;
  color: #60A5FA;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}
.search {
  width: 240px;
}
.notify :deep(.el-badge__content) {
  background: #F87171;
  border-color: #F87171;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 10px 4px 4px;
  background: #152330;
  border: 1px solid #1E2E41;
  border-radius: 24px;
  cursor: pointer;
  transition: all .2s;
  &:hover {
    border-color: #29405A;
    background: #1A2B3C;
  }
  .user-info {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
    .user-name {
      font-size: 13px;
      color: #F0F4F8;
      font-weight: 500;
    }
    .user-role {
      margin-top: 2px;
    }
  }
  .el-icon {
    color: #6B7C90;
    font-size: 12px;
  }
}

/* ----- Content ----- */
.content {
  flex: 1;
  overflow: auto;
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(37,208,125,0.05), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(96,165,250,0.05), transparent 60%),
    #0F1A24;
}

.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.notif-item {
  padding: 12px 16px;
  border-bottom: 1px solid #1E2E41;
  transition: background 0.2s;
}
.notif-item:hover { background: #0F1A24; }
.notif-item.danger { border-left: 3px solid #F56C6C; }
.notif-item.warning { border-left: 3px solid #E6A23C; }
.notif-item.success { border-left: 3px solid #67C23A; }
.notif-item.info { border-left: 3px solid #409EFF; }
.notif-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.notif-time {
  font-size: 11px;
  color: #6B7C90;
}
.notif-title {
  font-size: 14px;
  color: #D8E2EC;
  font-weight: 500;
  line-height: 1.4;
}
.notif-detail {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.5;
}
</style>
