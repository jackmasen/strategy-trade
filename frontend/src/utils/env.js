export const isDev = () => import.meta.env.DEV
export const isProd = () => import.meta.env.PROD

export const API_PREFIX = '/api/v1'

// 交易品种元数据
export const SYMBOL_META = {
  // ===== 加密货币 =====
  BTC:  { name: '比特币', color: '#F7931A', icon: '₿' },
  ETH:  { name: '以太坊', color: '#627EEA', icon: 'Ξ' },
  SOL:  { name: '索拉纳', color: '#9945FF', icon: '◎' },
  // ===== 贵金属 =====
  XAU:  { name: '黄金',   color: '#FBBF24', icon: '🥇' },
  XAG:  { name: '白银',   color: '#C0C0C0', icon: '🥈' },
  // ===== 能源 =====
  WTI:  { name: '原油',   color: '#6B7280', icon: '🛢️' },

  // ===== 美股-科技 =====
  TSLA: { name: '特斯拉', color: '#E31937', icon: 'T' },
  NVDA: { name: '英伟达', color: '#76B900', icon: 'N' },
  AAPL: { name: '苹果',   color: '#A2AAAD', icon: '' },
  MSFT: { name: '微软',   color: '#00A4EF', icon: 'M' },
  // ===== 美股-中概 =====
  TCEHY: { name: '腾讯',  color: '#0052D9', icon: '腾' },
  // ===== 美股-半导体 =====
  SKHYNIX: { name: 'SK海力士', color: '#FF6600', icon: 'H' },
  SNDK:    { name: '闪迪',     color: '#FF4444', icon: 'S' },
}

// 新闻来源（与 backend/models/analytics.py NewsArticle.SOURCE_* 严格一致）
export const NEWS_SOURCE_META = {
  1:  { name: 'CoinDesk',       short: 'CD',   type: 'crypto' },
  2:  { name: 'CoinTelegraph',  short: 'CT',   type: 'crypto' },
  3:  { name: 'Reuters',        short: 'RTR',  type: 'macro'  },
  4:  { name: 'Bloomberg',      short: 'BBG',  type: 'macro'  },
  5:  { name: 'CNBC',           short: 'CNBC', type: 'macro'  },
  6:  { name: 'OilPrice',       short: 'OIL',  type: 'energy' },
  7:  { name: '金十数据 Jin10', short: 'J10',  type: 'macro'  },
  8:  { name: 'Investing.com',  short: 'INV',  type: 'macro'  },
  9:  { name: 'MarketWatch',    short: 'MW',   type: 'macro'  },
  10: { name: 'FRED (美联储)',  short: 'FRED', type: 'official' },
  11: { name: 'EIA (能源署)',   short: 'EIA',  type: 'official' },
  12: { name: 'CME (FedWatch)', short: 'CME',  type: 'official' },
  99: { name: '自定义 Custom',  short: 'CUST', type: 'custom' },
}

// 交易所
export const EXCHANGE_META = {
  1: { name: '币安 Binance', color: '#F3BA2F' },
  2: { name: '欧易 OKX',     color: '#FFFFFF' },
}

// 订单方向
export const SIDE_META = {
  1: { name: '做多', class: 'profit' },
  2: { name: '做空', class: 'loss' },
}

// 订单状态
export const ORDER_STATUS_META = {
  0: { name: '待下单', type: 'info' },
  1: { name: '已提交', type: '' },
  2: { name: '已成交', type: 'success' },
  3: { name: '部分成交', type: 'warning' },
  4: { name: '已撤单', type: 'info' },
  5: { name: '失败', type: 'danger' },
  6: { name: '止盈成交', type: 'success' },
  7: { name: '止损成交', type: 'danger' },
  8: { name: '风控强平', type: 'danger' },
}

// 持仓状态
export const POSITION_STATUS_META = {
  1: { name: '持仓中', type: 'success' },
  2: { name: '已平仓', type: 'info' },
  3: { name: '已强平', type: 'danger' },
}

// 格式化辅助
export const fmtMoney = (v, digits = 2) => {
  if (v === null || v === undefined || v === '') return '--'
  const n = Number(v)
  if (!isFinite(n)) return '--'
  return n.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export const fmtPct = (v, digits = 2) => {
  if (v === null || v === undefined || v === '') return '--'
  const n = Number(v)
  if (!isFinite(n)) return '--'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

export const fmtPnlClass = (v) => {
  const n = Number(v)
  if (n > 0) return 'profit'
  if (n < 0) return 'loss'
  return 'neutral'
}

// 评分 → 等级
export const scoreLevel = (s) => {
  const n = Number(s) || 0
  if (n >= 8) return 'high'
  if (n >= 5) return 'good'
  if (n >= 3) return 'mid'
  return 'low'
}
