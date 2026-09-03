<template>
  <div class="page-container quant-signal-page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><TrendCharts /></el-icon>AI 量化信号引擎</h2>
        <div class="page-subtitle">
          7大因子综合评分：市场状态 · 资金流向 · 杠杆集中度 · 清算压力 · 波动率 · 新闻情绪 · 策略优势
        </div>
      </div>
      <div class="header-actions">
        <el-select v-model="timeframe" size="default" style="width: 100px; margin-right: 10px;" @change="loadOverview">
          <el-option label="1小时" value="1h" />
          <el-option label="4小时" value="4h" />
          <el-option label="日线" value="1d" />
        </el-select>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadOverview">
          刷新信号
        </el-button>
      </div>
    </div>

    <!-- 全币种信号概览 -->
    <div class="panel-card mb-16">
      <div class="panel-card__header">
        <span class="panel-card__title">全币种信号雷达</span>
        <span class="text-dim" style="font-size: 12px;">
          看涨 {{ stats.bullish }} · 看跌 {{ stats.bearish }} · 中性 {{ stats.neutral }}
        </span>
      </div>
      <div class="panel-card__body" v-loading="loading">
        <div class="signal-grid">
          <div
            v-for="sig in signals"
            :key="sig.symbol"
            class="signal-card"
            :class="[`signal-card--${sig.direction}`, { active: selectedSymbol === sig.symbol }]"
            @click="selectSymbol(sig.symbol)"
          >
            <div class="signal-card__header">
              <span class="signal-card__symbol">{{ sig.symbol }}</span>
              <el-tag
                size="small"
                effect="dark"
                :type="dirType(sig.direction)"
                class="signal-card__tag"
              >
                <span class="status-light" :class="sig.direction==='bullish'?'ok':(sig.direction==='bearish'?'error':'idle')" style="margin-right:2px;"></span>
                {{ sig.direction_cn }}
              </el-tag>
            </div>
            <div class="signal-card__score">
              <div class="score-bar">
                <div
                  class="score-bar__fill"
                  :class="`score-bar__fill--${sig.direction}`"
                  :style="{ width: sig.composite_score_pct + '%' }"
                ></div>
                <div class="score-bar__midline"></div>
              </div>
              <div class="score-value" :class="`score-value--${sig.direction}`">
                {{ sig.composite_score > 0 ? '+' : '' }}{{ sig.composite_score.toFixed(1) }}
              </div>
            </div>
            <div class="signal-card__meta">
              <div class="meta-item">
                <span class="meta-label">
                  <span class="status-light" :class="(sig.confidence||0)>=70?'ok':(sig.confidence>=50?'warn':'error')"></span>
                  置信度
                </span>
                <span class="meta-value">{{ sig.confidence?.toFixed(0) }}%</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">
                  <span class="status-light" :class="regimeClass(sig.market_regime)==='bullish'?'ok':(regimeClass(sig.market_regime)==='bearish'?'error':'idle')"></span>
                  状态
                </span>
                <span class="meta-value regime-tag">{{ sig.market_regime_cn }}</span>
              </div>
            </div>
            <div class="signal-card__price" v-if="sig.entry_price">
              ${{ formatPrice(sig.entry_price, sig.symbol) }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 选中币种的详细因子仪表盘 -->
    <div v-if="selectedSignal" class="factor-dashboard" v-loading="detailLoading">
      <!-- 左侧：综合信号 + 交易建议 -->
      <div class="panel-card factor-summary">
        <div class="panel-card__header">
          <span class="panel-card__title">{{ selectedSymbol }} 综合信号</span>
          <el-tag :type="dirType(selectedSignal.direction)" effect="dark" size="large">
            <span class="status-light" :class="selectedSignal.direction==='bullish'?'ok':(selectedSignal.direction==='bearish'?'error':'idle')" style="margin-right:4px;"></span>
            {{ selectedSignal.direction_cn }}
          </el-tag>
        </div>
        <div class="panel-card__body">
          <!-- 综合评分仪表盘 -->
          <div class="composite-gauge">
            <svg viewBox="0 0 200 120" class="gauge-svg">
              <defs>
                <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" style="stop-color:#EF4444;stop-opacity:1" />
                  <stop offset="50%" style="stop-color:#F59E0B;stop-opacity:1" />
                  <stop offset="100%" style="stop-color:#10B981;stop-opacity:1" />
                </linearGradient>
              </defs>
              <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#1F2937" stroke-width="16" stroke-linecap="round"/>
              <path
                d="M 20 100 A 80 80 0 0 1 180 100"
                fill="none"
                stroke="url(#gaugeGrad)"
                stroke-width="16"
                stroke-linecap="round"
                :stroke-dasharray="gaugeDashArray"
                stroke-dashoffset="0"
              />
              <!-- 指针 -->
              <line
                x1="100" y1="100"
                :x2="gaugeNeedleX" :y2="gaugeNeedleY"
                stroke="#fff" stroke-width="3" stroke-linecap="round"
              />
              <circle cx="100" cy="100" r="8" fill="#fff" />
            </svg>
            <div class="gauge-value">
              <span :class="`gauge-score--${selectedSignal.direction}`">
                {{ selectedSignal.composite_score > 0 ? '+' : '' }}{{ selectedSignal.composite_score.toFixed(2) }}
              </span>
              <span class="gauge-label">综合评分</span>
            </div>
          </div>

          <div class="confidence-bar">
            <div class="confidence-bar__label">
              <span>信号置信度</span>
              <span>{{ selectedSignal.confidence?.toFixed(1) }}%</span>
            </div>
            <el-progress
              :percentage="selectedSignal.confidence || 0"
              :color="confColor(selectedSignal.confidence)"
              :stroke-width="8"
              :show-text="false"
            />
          </div>

          <el-divider style="margin: 16px 0;" />

          <!-- 交易建议 -->
          <div class="trade-suggestion">
            <h4 class="section-title">交易建议</h4>
            <div class="suggestion-grid">
              <div class="suggestion-item">
                <span class="sug-label">入场价</span>
                <span class="sug-value">${{ formatPrice(selectedSignal.entry_price, selectedSymbol) }}</span>
              </div>
              <div class="suggestion-item">
                <span class="sug-label">止损价</span>
                <span class="sug-value sug-value--danger">${{ formatPrice(selectedSignal.stop_loss, selectedSymbol) }}</span>
              </div>
              <div class="suggestion-item">
                <span class="sug-label">止盈价</span>
                <span class="sug-value sug-value--success">${{ formatPrice(selectedSignal.take_profit, selectedSymbol) }}</span>
              </div>
              <div class="suggestion-item">
                <span class="sug-label">盈亏比</span>
                <span class="sug-value">{{ selectedSignal.risk_reward_ratio?.toFixed(2) }}:1</span>
              </div>
              <div class="suggestion-item">
                <span class="sug-label">建议杠杆</span>
                <span class="sug-value sug-value--warning">{{ selectedSignal.suggested_leverage }}x</span>
              </div>
              <div class="suggestion-item">
                <span class="sug-label">建议仓位</span>
                <span class="sug-value">{{ selectedSignal.position_size_pct }}%</span>
              </div>
            </div>
          </div>

          <el-divider style="margin: 16px 0;" />

          <!-- 市场状态 -->
          <div class="regime-info">
            <div class="regime-badge" :class="`regime-badge--${regimeClass(selectedSignal.market_regime)}`">
              <span class="status-light" :class="regimeClass(selectedSignal.market_regime)==='bullish'?'ok':(regimeClass(selectedSignal.market_regime)==='bearish'?'error':'idle')" style="margin-right:4px;"></span>
              {{ selectedSignal.market_regime_cn }}
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：7大因子详情 -->
      <div class="panel-card factor-details">
        <div class="panel-card__header">
          <span class="panel-card__title">7 大因子拆解</span>
        </div>
        <div class="panel-card__body">
          <div
            v-for="factor in factorList"
            :key="factor.key"
            class="factor-row"
          >
            <div class="factor-header">
              <div class="factor-icon" :style="{ background: factor.color + '20', color: factor.color }">
                {{ factor.icon }}
              </div>
              <div class="factor-info">
                <div class="factor-name">{{ factor.name }}</div>
                <div class="factor-sub">
                  权重 {{ (factor.weight * 100).toFixed(0) }}% · 
                  置信 {{ factor.confidence?.toFixed(0) }}%
                </div>
              </div>
              <div class="factor-score" :class="`factor-score--${factor.direction}`">
                {{ factor.score > 0 ? '+' : '' }}{{ factor.score?.toFixed(2) }}
              </div>
            </div>
            <div class="factor-bar">
              <div class="factor-bar__bg">
                <div
                  class="factor-bar__fill"
                  :class="factor.direction"
                  :style="{ width: factor.score_pct + '%' }"
                ></div>
              </div>
            </div>
            <div class="factor-details" v-if="factor.details">
              <el-collapse>
                <el-collapse-item title="查看详情" :name="factor.key">
                  <div class="detail-grid">
                    <div v-for="(val, key) in factor.details" :key="key" class="detail-item">
                      <span class="detail-label">{{ formatDetailLabel(key) }}</span>
                      <span class="detail-value">{{ formatDetailValue(val, key) }}</span>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 市场全景：谁在交易 · 资金在哪里 · 杠杆在哪里 -->
    <div class="panel-card mb-16">
      <div class="panel-card__header">
        <span class="panel-card__title">市场全景透视</span>
        <span class="text-dim" style="font-size: 12px;">实时资金流 · 杠杆分布 · 清算热力</span>
      </div>
      <div class="panel-card__body">
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="market-perspective">
              <div class="perspective-title">
                <el-icon color="#10B981"><TrendCharts /></el-icon>
                资金流向
              </div>
              <div class="perspective-list">
                <div v-for="sig in topFlows" :key="sig.symbol" class="perspective-item">
                  <span class="pers-symbol">{{ sig.symbol }}</span>
                  <div class="pers-bar">
                    <div
                      class="pers-bar__fill"
                      :class="sig.factors?.capital_flow?.direction"
                      :style="{ width: Math.abs(sig.factors?.capital_flow?.score || 0) / 10 * 100 + '%' }"
                    ></div>
                  </div>
                  <span class="pers-value" :class="sig.factors?.capital_flow?.direction">
                    {{ (sig.factors?.capital_flow?.score || 0) > 0 ? '+' : '' }}{{ sig.factors?.capital_flow?.score?.toFixed(1) }}
                  </span>
                </div>
              </div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="market-perspective">
              <div class="perspective-title">
                <el-icon color="#F59E0B"><Lightning /></el-icon>
                杠杆集中度
              </div>
              <div class="perspective-list">
                <div v-for="sig in signals" :key="sig.symbol" class="perspective-item">
                  <span class="pers-symbol">{{ sig.symbol }}</span>
                  <div class="pers-bar">
                    <div
                      class="pers-bar__fill"
                      :class="sig.factors?.leverage?.direction"
                      :style="{ width: Math.abs(sig.factors?.leverage?.score || 0) / 10 * 100 + '%' }"
                    ></div>
                  </div>
                  <span class="pers-value" :class="sig.factors?.leverage?.direction">
                    {{ (sig.factors?.leverage?.score || 0) > 0 ? '+' : '' }}{{ sig.factors?.leverage?.score?.toFixed(1) }}
                  </span>
                </div>
              </div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="market-perspective">
              <div class="perspective-title">
                <el-icon color="#EF4444"><Promotion /></el-icon>
                清算压力
              </div>
              <div class="perspective-list">
                <div v-for="sig in signals" :key="sig.symbol" class="perspective-item">
                  <span class="pers-symbol">{{ sig.symbol }}</span>
                  <div class="pers-bar">
                    <div
                      class="pers-bar__fill"
                      :class="sig.factors?.liquidation?.direction"
                      :style="{ width: Math.abs(sig.factors?.liquidation?.score || 0) / 10 * 100 + '%' }"
                    ></div>
                  </div>
                  <span class="pers-value" :class="sig.factors?.liquidation?.direction">
                    {{ (sig.factors?.liquidation?.score || 0) > 0 ? '+' : '' }}{{ sig.factors?.liquidation?.score?.toFixed(1) }}
                  </span>
                </div>
              </div>
            </div>
          </el-col>
        </el-row>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { TrendCharts, Refresh, Lightning, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { http, API_PREFIX } from '@/utils/request'

const loading = ref(false)
const detailLoading = ref(false)
const timeframe = ref('4h')
const signals = ref([])
const selectedSymbol = ref('BTC')
const selectedSignal = ref(null)

const stats = computed(() => ({
  bullish: signals.value.filter(s => s.direction === 'bullish').length,
  bearish: signals.value.filter(s => s.direction === 'bearish').length,
  neutral: signals.value.filter(s => s.direction === 'neutral').length,
}))

const topFlows = computed(() => {
  return [...signals.value].sort((a, b) => {
    const sa = a.factors?.capital_flow?.score || 0
    const sb = b.factors?.capital_flow?.score || 0
    return Math.abs(sb) - Math.abs(sa)
  })
})

const factorList = computed(() => {
  if (!selectedSignal.value?.factors) return []
  const factorInfo = {
    market_regime: { name: '市场状态', icon: '📊', color: '#3B82F6' },
    capital_flow: { name: '资金流向', icon: '💰', color: '#10B981' },
    leverage: { name: '杠杆集中度', icon: '⚡', color: '#F59E0B' },
    liquidation: { name: '清算压力', icon: '🔥', color: '#EF4444' },
    volatility: { name: '波动率', icon: '🌊', color: '#8B5CF6' },
    news_sentiment: { name: '新闻情绪', icon: '📰', color: '#EC4899' },
    strategy_advantage: { name: '策略优势', icon: '🎯', color: '#06B6D4' },
  }
  return Object.entries(selectedSignal.value.factors).map(([key, val]) => ({
    key,
    ...factorInfo[key],
    ...val,
    score_pct: ((val.score + 10) / 20 * 100),
  }))
})

const gaugeDashArray = computed(() => {
  // 半圆周长 = π * r = 3.14 * 80 = 251.2
  const total = 251.2
  const score = selectedSignal.value?.composite_score || 0
  const pct = (score + 10) / 20
  return `${total * pct} ${total}`
})

const gaugeNeedleX = computed(() => {
  const score = selectedSignal.value?.composite_score || 0
  const pct = (score + 10) / 20
  const angle = Math.PI * pct  // 0 to PI
  return 100 + 70 * Math.cos(Math.PI - angle)
})

const gaugeNeedleY = computed(() => {
  const score = selectedSignal.value?.composite_score || 0
  const pct = (score + 10) / 20
  const angle = Math.PI * pct
  return 100 - 70 * Math.sin(angle)
})

function dirType(dir) {
  return dir === 'bullish' ? 'success' : dir === 'bearish' ? 'danger' : 'info'
}

function confColor(conf) {
  if (conf >= 70) return '#10B981'
  if (conf >= 50) return '#F59E0B'
  return '#9CA3AF'
}

function regimeClass(regime) {
  if (!regime) return 'ranging'
  if (regime.includes('up') || regime.includes('breakout_up')) return 'bullish'
  if (regime.includes('down') || regime.includes('breakout_down')) return 'bearish'
  return 'ranging'
}

function formatPrice(price, symbol) {
  if (!price) return '0'
  if (['XAU', 'WTI'].includes(symbol)) return price.toFixed(2)
  if (price > 1000) return price.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (price > 100) return price.toFixed(2)
  return price.toFixed(4)
}

function formatDetailLabel(key) {
  const labels = {
    regime: '市场状态',
    adx: 'ADX',
    ma_slope_pct: 'MA斜率(%)',
    bb_width_pct: '布林带宽度(%)',
    trend_strength: '趋势强度',
    vol_ratio: '波动率比',
    vwap: 'VWAP',
    vwap_deviation_pct: 'VWAP偏离(%)',
    obv_change_pct: 'OBV变化(%)',
    mfi: 'MFI资金指数',
    oi_change_pct_20p: 'OI变化(20期%)',
    funding_rate_pct: '资金费率(%)',
    funding_annualized_pct: '年化费率(%)',
    long_short_ratio: '多空比',
    crowding_level: '拥挤度',
    liquidation_above_5pct_pct: '上方清算(%)',
    liquidation_below_5pct_pct: '下方清算(%)',
    total_liquidity_zone_pct: '清算区总量(%)',
    imbalance: '清算失衡',
    cascade_risk: '瀑布风险',
    realized_vol_20d_pct: '20日波动率(%)',
    realized_vol_60d_pct: '60日波动率(%)',
    vol_ratio_20_60: '波动率比(20/60)',
    atr_pct: 'ATR(%)',
    vol_state: '波动状态',
    sentiment_score: '情绪得分',
    news_count_24h: '24h新闻数',
    news_density_ratio: '新闻密度比',
    max_event_impact: '最大事件影响',
    is_extreme: '是否极值',
    best_strategy: '最优策略',
    best_score: '最优得分',
    rankings: '策略排名',
  }
  return labels[key] || key
}

function formatDetailValue(val, key) {
  if (typeof val === 'boolean') return val ? '是' : '否'
  if (typeof val === 'object') return JSON.stringify(val)
  return val
}

async function loadOverview() {
  loading.value = true
  try {
    const res = await http.get(`${API_PREFIX}/quant-signal/overview`, {
      params: { symbols: 'BTC,ETH,SOL,XAU,WTI', timeframe: timeframe.value }
    })
    signals.value = res.signals || []
    if (!selectedSignal.value && signals.value.length > 0) {
      selectSymbol(signals.value[0].symbol)
    } else if (selectedSymbol.value) {
      const found = signals.value.find(s => s.symbol === selectedSymbol.value)
      if (found) selectedSignal.value = found
    }
  } catch (e) {
    ElMessage.error('加载信号失败')
  } finally {
    loading.value = false
  }
}

function selectSymbol(sym) {
  selectedSymbol.value = sym
  const found = signals.value.find(s => s.symbol === sym)
  if (found) {
    selectedSignal.value = found
  }
}

onMounted(() => {
  loadOverview()
})
</script>

<style scoped>
.quant-signal-page {
  padding-bottom: 40px;
}

.header-actions {
  display: flex;
  align-items: center;
}

/* 信号卡片网格 */
.signal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.signal-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.signal-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: #6B7280;
}

.signal-card--bullish::before { background: #10B981; }
.signal-card--bearish::before { background: #EF4444; }
.signal-card--neutral::before { background: #6B7280; }

.signal-card:hover {
  border-color: var(--primary-color);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.signal-card.active {
  border-color: var(--primary-color);
  background: var(--primary-color) + '10';
}

.signal-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.signal-card__symbol {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.signal-card__tag {
  font-size: 11px;
}

.signal-card__score {
  margin-bottom: 10px;
}

.score-bar {
  height: 8px;
  background: #1F2937;
  border-radius: 4px;
  position: relative;
  overflow: hidden;
  margin-bottom: 4px;
}

.score-bar__midline {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: rgba(255,255,255,0.2);
}

.score-bar__fill {
  height: 100%;
  border-radius: 4px;
  position: absolute;
  top: 0;
  left: 50%;
  transform-origin: left;
}

.score-bar__fill--bullish {
  background: linear-gradient(90deg, #10B981, #34D399);
  transform: scaleX(var(--w, 0.5));
}

.score-bar__fill--bearish {
  background: linear-gradient(90deg, #EF4444, #F87171);
  transform: scaleX(var(--w, 0.5)) translateX(-100%);
  transform-origin: right;
}

.score-bar__fill--neutral {
  background: #6B7280;
  width: 0 !important;
}

.score-value {
  font-size: 14px;
  font-weight: 600;
  text-align: right;
}
.score-value--bullish { color: #10B981; }
.score-value--bearish { color: #EF4444; }
.score-value--neutral { color: #6B7280; }

.signal-card__meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-label {
  font-size: 11px;
  color: var(--text-dim);
}

.meta-value {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}

.regime-tag {
  font-size: 11px;
  color: var(--text-dim);
}

.signal-card__price {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

/* 因子仪表盘 */
.factor-dashboard {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.factor-summary {
  margin-bottom: 0;
}

.factor-details {
  margin-bottom: 0;
}

.composite-gauge {
  text-align: center;
  padding: 10px 0;
}

.gauge-svg {
  width: 180px;
  height: 110px;
}

.gauge-value {
  margin-top: -10px;
}

.gauge-score {
  font-size: 32px;
  font-weight: 700;
  display: block;
}
.gauge-score--bullish { color: #10B981; }
.gauge-score--bearish { color: #EF4444; }
.gauge-score--neutral { color: #6B7280; }

.gauge-label {
  font-size: 12px;
  color: var(--text-dim);
}

.confidence-bar {
  margin-top: 16px;
}

.confidence-bar__label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 6px;
  color: var(--text-secondary);
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px 0;
}

.suggestion-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.suggestion-item {
  background: var(--bg-secondary);
  padding: 10px 12px;
  border-radius: 8px;
}

.sug-label {
  display: block;
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.sug-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.sug-value--success { color: #10B981; }
.sug-value--danger { color: #EF4444; }
.sug-value--warning { color: #F59E0B; }

.regime-info {
  text-align: center;
}

.regime-badge {
  display: inline-block;
  padding: 8px 20px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
}

.regime-badge--bullish {
  background: rgba(16, 185, 129, 0.15);
  color: #10B981;
}

.regime-badge--bearish {
  background: rgba(239, 68, 68, 0.15);
  color: #EF4444;
}

.regime-badge--ranging {
  background: rgba(107, 114, 128, 0.15);
  color: #9CA3AF;
}

/* 因子行 */
.factor-row {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
}

.factor-row:last-child {
  border-bottom: none;
}

.factor-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.factor-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.factor-info {
  flex: 1;
}

.factor-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.factor-sub {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}

.factor-score {
  font-size: 16px;
  font-weight: 700;
  min-width: 50px;
  text-align: right;
}
.factor-score--bullish { color: #10B981; }
.factor-score--bearish { color: #EF4444; }
.factor-score--neutral { color: #6B7280; }

.factor-bar__bg {
  height: 6px;
  background: #1F2937;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.factor-bar__bg::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: rgba(255,255,255,0.15);
}

.factor-bar__fill {
  height: 100%;
  position: absolute;
  top: 0;
  border-radius: 3px;
}

.factor-bar__fill.bullish {
  background: linear-gradient(90deg, #10B981, #34D399);
  left: 50%;
}

.factor-bar__fill.bearish {
  background: linear-gradient(90deg, #EF4444, #F87171);
  right: 50%;
}

.factor-bar__fill.neutral {
  width: 0 !important;
}

.factor-details {
  margin-top: 8px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.detail-label {
  color: var(--text-dim);
}

.detail-value {
  color: var(--text-secondary);
  font-weight: 500;
}

/* 市场全景 */
.market-perspective {
  background: var(--bg-secondary);
  border-radius: 10px;
  padding: 14px;
}

.perspective-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.perspective-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.perspective-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pers-symbol {
  width: 40px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.pers-bar {
  flex: 1;
  height: 6px;
  background: #1F2937;
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}

.pers-bar__fill {
  height: 100%;
  border-radius: 3px;
}

.pers-bar__fill.bullish {
  background: #10B981;
  margin-left: auto;
}

.pers-bar__fill.bearish {
  background: #EF4444;
}

.pers-bar__fill.neutral {
  width: 0 !important;
}

.pers-value {
  width: 40px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
}

.pers-value.bullish { color: #10B981; }
.pers-value.bearish { color: #EF4444; }
.pers-value.neutral { color: #6B7280; }
</style>
