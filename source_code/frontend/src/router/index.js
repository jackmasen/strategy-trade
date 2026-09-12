import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/store/user'

const routes = [
  // ---------- 登录 ----------
  {
    path: '/login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true },
  },

  // ---------- 主布局（带侧边栏+顶部） ----------
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '数据大屏', icon: 'Monitor', menuKey: 'dashboard' },
      },
      {
        path: 'exchange',
        name: 'Exchange',
        component: () => import('@/views/Exchange.vue'),
        meta: { title: '交易所子账号', icon: 'Wallet', menuKey: 'exchange' },
      },
      {
        path: 'strategy',
        name: 'Strategy',
        component: () => import('@/views/Strategy.vue'),
        meta: { title: '策略管理', icon: 'DataAnalysis', menuKey: 'strategy' },
      },
      {
        path: 'trade',
        name: 'Trade',
        component: () => import('@/views/Trade.vue'),
        meta: { title: '交易订单', icon: 'TrendCharts', menuKey: 'trade' },
      },
      {
        path: 'kline',
        name: 'Kline',
        component: () => import('@/views/Kline.vue'),
        meta: { title: 'K线行情', icon: 'DataLine', menuKey: 'kline' },
      },
      {
        path: 'positions',
        name: 'Positions',
        component: () => import('@/views/Positions.vue'),
        meta: { title: '当前持仓', icon: 'PieChart', menuKey: 'positions' },
      },
      {
        path: 'news',
        name: 'News',
        component: () => import('@/views/News.vue'),
        meta: { title: '新闻情绪', icon: 'Reading', menuKey: 'news' },
      },
      {
        path: 'ai',
        name: 'AI',
        component: () => import('@/views/AI.vue'),
        meta: { title: 'AI实时分析', icon: 'Cpu', menuKey: 'ai' },
      },
      {
        path: 'quant-signal',
        name: 'QuantSignal',
        component: () => import('@/views/QuantSignal.vue'),
        meta: { title: '量化信号引擎', icon: 'TrendCharts', menuKey: 'quant-signal' },
      },
      {
        path: 'evolution',
        name: 'Evolution',
        component: () => import('@/views/Evolution.vue'),
        meta: { title: '策略自我进化', icon: 'MagicStick', menuKey: 'evolution' },
      },
      {
        path: 'backtest',
        name: 'Backtest',
        component: () => import('@/views/Backtest.vue'),
        meta: { title: '历史回测', icon: 'Histogram', menuKey: 'backtest' },
      },
      {
        path: 'risk',
        name: 'Risk',
        component: () => import('@/views/Risk.vue'),
        meta: { title: '风控中心', icon: 'Warning', menuKey: 'risk' },
      },
      {
        path: 'reports',
        name: 'Reports',
        component: () => import('@/views/Reports.vue'),
        meta: { title: '财务报表', icon: 'Document', menuKey: 'reports' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue'),
        meta: { title: '用户管理', icon: 'User', menuKey: 'users', adminOnly: true },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
        meta: { title: '系统设置', icon: 'Setting', menuKey: 'settings', adminOnly: true },
      },
      {
        path: 'crawler-health',
        name: 'CrawlerHealth',
        component: () => import('@/views/CrawlerHealth.vue'),
        meta: { title: '爬虫监控', icon: 'Monitor', menuKey: 'crawler-health' },
      },
      {
        path: 'monitor',
        name: 'SystemMonitor',
        component: () => import('@/views/SystemMonitor.vue'),
        meta: { title: '系统监控', icon: 'Monitor', menuKey: 'monitor', adminOnly: true },
      },
      {
        path: 'system',
        name: 'SystemAdmin',
        component: () => import('@/views/SystemAdmin.vue'),
        meta: { title: '系统管理', icon: 'Monitor', menuKey: 'system', adminOnly: true },
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '个人中心', hideMenu: true },
      },
    ],
  },

  // ---------- 404 ----------
  {
    path: '/:pathMatch(.*)*',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '页面不存在', public: true },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// ---------- 登录守卫 ----------
router.beforeEach((to, _from, next) => {
  const user = useUserStore()
  const title = to.meta?.title
  if (title) {
    document.title = `${title} · 策略交易系统`
  }
  if (to.meta?.public) {
    if (to.path === '/login' && user.isLoggedIn) {
      return next('/')
    }
    return next()
  }
  if (!user.isLoggedIn) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  // adminOnly 页面
  if (to.meta?.adminOnly && !user.isAdmin) {
    return next('/')
  }
  next()
})

export default router
