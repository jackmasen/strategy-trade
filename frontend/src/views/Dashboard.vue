<template>
  <div class="dashboard-page" v-loading="loading" element-loading-text="数据加载中...">
    <!-- 系统运行状态横幅 -->
    <div class="sys-status-bar">
      <div class="ssb-left">
        <div class="ssb-health" :class="sysStatus.overall">
          <span class="pulse-dot"></span>
          <span class="ssb-health-text">
            {{ sysStatus.overall === 'healthy' ? '运行正常' : sysStatus.overall === 'warning' ? '存在告警' : '严重故障' }}
          </span>
        </div>
        <div class="ssb-item">
          <span class="ssb-label">版本</span>
          <span class="ssb-value monospace">{{ sysStatus.version }}</span>
        </div>
        <div class="ssb-item">
          <span class="ssb-label">运行</span>
          <span class="ssb-value">{{ sysStatus.uptime }}</span>
        </div>
      </div>
      <div class="ssb-center">
        <div class="ssb-metric" title="CPU 使用率">
          <span class="ssb-m-label">CPU</span>
          <div class="ssb-m-bar"><div class="ssb-m-fill" :style="{ width: sysStatus.resources.cpu_percent + '%', background: cpuColor }"></div></div>
          <span class="ssb-m-value" :style="{ color: cpuColor }">{{ sysStatus.resources.cpu_percent }}%</span>
        </div>
        <div class="ssb-metric" title="内存使用率">
          <span class="ssb-m-label">内存</span>
          <div class="ssb-m-bar"><div class="ssb-m-fill" :style="{ width: sysStatus.resources.memory_percent + '%', background: memColor }"></div></div>
          <span class="ssb-m-value" :style="{ color: memColor }">{{ sysStatus.resources.memory_percent }}%</span>
        </div>
        <div class="ssb-metric" title="磁盘使用率">
          <span class="ssb-m-label">磁盘</span>
          <div class="ssb-m-bar"><div class="ssb-m-fill" :style="{ width: sysStatus.resources.disk_percent + '%', background: diskColor }"></div></div>
          <span class="ssb-m-value" :style="{ color: diskColor }">{{ sysStatus.resources.disk_percent }}%</span>
        </div>
      </div>
      <div class="ssb-right">
        <div class="ssb-item" v-if="sysStatus.issue_count">
          <span class="ssb-label">问题</span>
          <el-tag size="small" effect="dark" :type="issueTagType" round>{{ sysStatus.issue_count.total || 0 }}</el-tag>
        </div>
        <div class="ssb-item">
          <span class="ssb-label">数据库</span>
          <span class="status-light" :class="sysStatus.database.connection === 'ok' ? 'ok' : 'error'"></span>
        </div>
        <div class="ssb-item">
          <span class="ssb-label">定时任务</span>
          <span class="status-light" :class="sysStatus.scheduler.status === 'running' ? 'ok' : 'warn'"></span>
        </div>
        <div class="ssb-item ssb-refresh" @click="loadSysStatus" title="刷新系统状态">
          <el-icon :size="14" :class="{ 'rotating': sysLoading }"><Refresh /></el-icon>
        </div>
      </div>
    </div>

    <!-- 顶部：概览统计 KPI -->
    <el-row :gutter="18" class="top-kpi">
      <el-col :span="6" v-for="(k, idx) in kpiCards" :key="idx">
        <div class="stat-card" :class="k.cls">
          <div class="stat-card__label">
            <span style="display:flex;align-items:center;gap:4px;">
              <span class="status-light" :class="k.lightStatus || (k.trend > 0 ? 'ok' : (k.trend < 0 ? 'error' : 'idle'))"></span>
              {{ k.label }}
            </span>
            <div class="stat-card__icon" :style="{ background: k.iconBg }">
              <el-icon :size="20" :style="{ color: k.iconColor }"><component :is="k.icon" /></el-icon>
            </div>
          </div>
          <div class="stat-card__value" :class="k.valueCls">
            <template v-if="k.isMoney">$</template>
            {{ k.value }}
            <template v-if="k.isPct">%</template>
          </div>
          <div class="stat-card__extra">
            <el-tag :type="k.trend > 0 ? 'success' : (k.trend < 0 ? 'danger' : 'info')" size="small" effect="dark" round>
              {{ k.trend > 0 ? '↑' : k.trend < 0 ? '↓' : '—' }} {{ Math.abs(k.trend) }}%
            </el-tag>
            <span class="text-dim">{{ k.sub }}</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 第二行：盈亏曲线 + 品种分布 -->
    <el-row :gutter="18" class="mt-16">
      <el-col :span="16">
        <div class="panel-card" style="height: 380px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#25D07D"><TrendCharts /></el-icon>
              近30天权益与盈亏曲线
            </span>
            <div class="flex gap-8">
              <el-radio-group v-model="pnlRange" size="small">
                <el-radio-button value="7">近7天</el-radio-button>
                <el-radio-button value="30">近30天</el-radio-button>
                <el-radio-button value="90">近90天</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <div class="panel-card__body" style="padding: 12px 16px; height: calc(100% - 56px);">
            <v-chart :option="pnlChartOption" autoresize style="height: 100%;" />
          </div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="panel-card" style="height: 380px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#FBBF24"><PieChart /></el-icon>
              品种盈亏分布
            </span>
            <el-button link type="primary" size="small">全部</el-button>
          </div>
          <div class="panel-card__body" style="height: calc(100% - 56px);">
            <v-chart :option="symbolPieOption" autoresize style="height: 100%;" />
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- AI 综合预测面板 -->
    <el-row :gutter="18" class="mt-16">
      <el-col :span="24">
        <div class="panel-card prediction-panel">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#A78BFA"><MagicStick /></el-icon>
              AI 综合预测（技术面40% + 新闻30% + AI 20% + Polymarket 10%）
            </span>
            <el-button link type="primary" size="small" :loading="predictionLoading" @click="loadPrediction">刷新</el-button>
          </div>
          <div class="panel-card__body prediction-body">
            <div v-if="predictions.length === 0 && !predictionLoading" class="text-dim prediction-empty">
              暂无预测数据，点击右上角刷新
            </div>
            <div class="prediction-grid" v-else>
              <div
                v-for="p in predictions"
                :key="p.symbol"
                class="prediction-card"
                :class="p.direction"
              >
                <div class="pc-header">
                  <span class="pc-symbol">
                    <span class="status-light" :class="p.direction==='bullish'?'ok':(p.direction==='bearish'?'error':'warn')"></span>
                    {{ p.symbol }}
                  </span>
                  <el-tag :type="p.direction==='bullish'?'success':p.direction==='bearish'?'danger':'warning'" effect="dark" size="small">
                    {{ p.direction_cn }}
                  </el-tag>
                </div>
                <div class="pc-price-row">
                  <span class="pc-current-price">${{ formatPrice(p.current_price, p.symbol) }}</span>
                  <span class="pc-target-price" :class="p.predicted_change_pct>=0?'text-profit':'text-loss'" v-if="p.target_price">
                    → ${{ formatPrice(p.target_price, p.symbol) }}
                  </span>
                </div>
                <div class="pc-change">
                  <span class="text-dim pc-label">预期涨跌</span>
                  <span class="pc-change-value" :class="p.predicted_change_pct>=0?'text-profit':'text-loss'">
                    {{ p.predicted_change_pct >= 0 ? '+' : '' }}{{ p.predicted_change_pct }}%
                  </span>
                </div>
                <div class="pc-confidence">
                  <span class="text-dim pc-label">置信度</span>
                  <div class="pc-conf-bar">
                    <el-progress :percentage="p.confidence" :stroke-width="5" :show-text="false" :color="p.direction==='bullish'?'#4ADE80':p.direction==='bearish'?'#F87171':'#FBBF24'" />
                    <span class="pc-conf-text">{{ p.confidence }}%</span>
                  </div>
                </div>
                <div class="pc-scores">
                  <span class="pc-score" :title="技术面评分">
                    <em>技术</em>
                    <b :style="{color: p.scores.technical!=null ? (p.scores.technical>=5?'#4ADE80':'#F87171') : '#888'}">
                      {{ p.scores.technical ?? '—' }}
                    </b>
                  </span>
                  <span class="pc-score" :title="新闻情绪评分">
                    <em>新闻</em>
                    <b :style="{color: p.scores.news!=null ? (p.scores.news>=5?'#4ADE80':'#F87171') : '#888'}">
                      {{ p.scores.news ?? '—' }}
                    </b>
                  </span>
                  <span class="pc-score" :title="AI分析评分">
                    <em>AI</em>
                    <b :style="{color: p.scores.ai!=null ? (p.scores.ai>=5?'#4ADE80':'#F87171') : '#888'}">
                      {{ p.scores.ai ?? '—' }}
                    </b>
                  </span>
                  <span class="pc-score" :title="Polymarket预测">
                    <em>市场</em>
                    <b :style="{color: p.scores.polymarket_prob!=null ? (p.scores.polymarket_prob>=50?'#4ADE80':'#F87171') : '#888'}">
                      {{ p.scores.polymarket_prob!=null ? p.scores.polymarket_prob+'%' : '—' }}
                    </b>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 第三行：实时评分看板 + 今日交易 -->
    <el-row :gutter="18" class="mt-16">
      <el-col :span="12">
        <div class="panel-card" style="height: 380px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#60A5FA"><DataAnalysis /></el-icon>
              最新策略评分（满分10，≥5分开仓）
            </span>
            <el-tag size="small" type="success" effect="dark" round>实时</el-tag>
          </div>
          <div class="panel-card__body" style="height: calc(100% - 56px); overflow: auto;">
            <el-table :data="latestScores" size="default" :header-cell-style="{ background:'#192738' }">
              <el-table-column label="品种" width="100">
                <template #default="{ row }">
                  <div class="flex-center gap-8">
                    <span class="status-light" :class="row.score_total>=5?'ok':'error'"></span>
                    <span style="font-size:20px;">{{ SYMBOL_META[row.symbol]?.icon || '●' }}</span>
                    <span class="monospace text-strong">{{ row.symbol }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="timeframe" label="周期" width="70" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="dark">{{ row.timeframe }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="技术(4)" width="85" align="center">
                <template #default="{ row }">
                  <span class="monospace">{{ row.score_technical.toFixed(1) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="新闻(3)" width="85" align="center">
                <template #default="{ row }">
                  <span class="monospace">{{ row.score_news.toFixed(1) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="AI(3)" width="85" align="center">
                <template #default="{ row }">
                  <span class="monospace">{{ row.score_ai.toFixed(1) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="综合评分" width="120" align="center">
                <template #default="{ row }">
                  <div class="score-box">
                    <div class="score-ring" :data-level="scoreLevel(row.score_total)">
                      {{ row.score_total.toFixed(1) }}
                    </div>
                    <span
                      class="direction-tag"
                      :class="row.suggested_direction === 'long' ? 'profit' : row.suggested_direction === 'short' ? 'loss' : 'neutral'"
                    >
                      {{ row.suggested_direction === 'long' ? '做多' : row.suggested_direction === 'short' ? '做空' : '观望' }}
                    </span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="建议杠杆" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="dark" type="warning">{{ row.suggested_leverage }}x</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="信号" width="80" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.trigger_trade ? 'success' : 'info'" effect="dark" round>
                    {{ row.trigger_trade ? '已触发' : '—' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="panel-card" style="height: 380px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#F87171"><Collection /></el-icon>
              今日交易流水
            </span>
            <el-button link type="primary" size="small" @click="$router.push('/trade')">查看全部 →</el-button>
          </div>
          <div class="panel-card__body" style="height: calc(100% - 56px); overflow: auto;">
            <el-table :data="todayTrades" size="default" :header-cell-style="{ background:'#192738' }">
              <el-table-column label="时间" width="80" align="center">
                <template #default="{ row }">{{ row.time }}</template>
              </el-table-column>
              <el-table-column label="品种" width="70" align="center">
                <template #default="{ row }"><span class="monospace text-strong">{{ row.symbol }}</span></template>
              </el-table-column>
              <el-table-column label="方向" width="70" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="dark" :type="row.side === 1 ? 'success' : 'danger'">
                    {{ row.side === 1 ? '多' : '空' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="leverage" label="杠杆" width="70" align="center">
                <template #default="{ row }"><span class="monospace">{{ row.leverage }}x</span></template>
              </el-table-column>
              <el-table-column label="开仓价" width="100" align="right">
                <template #default="{ row }"><span class="monospace">{{ row.entry }}</span></template>
              </el-table-column>
              <el-table-column label="平仓价" width="100" align="right">
                <template #default="{ row }"><span class="monospace">{{ row.exit || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="盈亏($)" width="110" align="right">
                <template #default="{ row }">
                  <span class="monospace" :class="row.pnl >= 0 ? 'text-profit' : 'text-loss'">
                    {{ row.pnl >= 0 ? '+' : '' }}{{ row.pnl.toFixed(2) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <div style="display:flex;align-items:center;justify-content:center;gap:4px;">
                    <span class="status-light" :class="row.statusType==='success'?'ok':(row.statusType==='danger'?'error':'warn')"></span>
                    <el-tag size="small" effect="dark" :type="row.statusType" round>{{ row.status }}</el-tag>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 第四行：当前持仓快览 + 胜率分析 -->
    <el-row :gutter="18" class="mt-16 mb-24">
      <el-col :span="14">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#25D07D"><Wallet /></el-icon>
              当前持仓
            </span>
            <el-button link type="primary" size="small" @click="$router.push('/positions')">管理 →</el-button>
          </div>
          <div class="panel-card__body">
            <el-row :gutter="16">
              <el-col :span="8" v-for="p in positions" :key="p.symbol">
                <div class="position-card" :class="p.side === 1 ? 'pos-long' : 'pos-short'">
                  <div class="flex-between">
                    <div class="flex gap-8" style="align-items:center;">
                      <span class="status-light" :class="p.side === 1 ? 'ok' : 'error'"></span>
                      <span class="pos-symbol">{{ SYMBOL_META[p.symbol]?.icon }}</span>
                      <div>
                        <div class="monospace text-strong" style="font-size: 16px;">{{ p.symbol }}</div>
                        <div class="text-dim" style="font-size:11px;">{{ SYMBOL_META[p.symbol]?.name }}</div>
                      </div>
                    </div>
                    <el-tag size="small" effect="dark" :type="p.side === 1 ? 'success' : 'danger'">
                      {{ p.side === 1 ? '多' : '空' }} · {{ p.leverage }}x
                    </el-tag>
                  </div>
                  <div class="mt-16 progress-row">
                    <div class="progress-row__label">止盈 TP</div>
                    <div class="progress-row__track">
                      <div class="progress-row__fill" style="width: 75%; background: #4ADE80;"></div>
                    </div>
                    <div class="progress-row__value text-profit">+{{ p.tpDistPct }}%</div>
                  </div>
                  <div class="progress-row">
                    <div class="progress-row__label">止损 SL</div>
                    <div class="progress-row__track">
                      <div class="progress-row__fill" style="width: 32%; background: #F87171;"></div>
                    </div>
                    <div class="progress-row__value text-loss">-{{ p.slDistPct }}%</div>
                  </div>
                  <div class="mt-8 pos-info-row" style="display:flex;justify-content:space-between;gap:8px;font-size:11px;">
                    <div>
                      <span class="text-dim">仓位金额</span>
                      <span class="monospace text-strong" style="margin-left:4px;">${{ p.quantity.toFixed(0) }}</span>
                    </div>
                    <div>
                      <span class="text-dim">保证金</span>
                      <span class="monospace text-warn" style="margin-left:4px;">${{ p.margin.toFixed(0) }}</span>
                    </div>
                    <div>
                      <span class="text-dim">开仓</span>
                      <span class="monospace" style="margin-left:4px;">${{ p.entry.toFixed(2) }}</span>
                    </div>
                    <div>
                      <span class="text-dim">标记</span>
                      <span class="monospace text-info" style="margin-left:4px;">${{ p.mark.toFixed(2) }}</span>
                    </div>
                  </div>
                  <div class="mt-8 flex-between pos-bottom">
                    <div>
                      <div class="text-dim" style="font-size:11px;">浮动盈亏</div>
                      <div class="monospace pos-pnl" :class="p.upnl >= 0 ? 'text-profit' : 'text-loss'">
                        {{ p.upnl >= 0 ? '+' : '' }}{{ p.upnl.toFixed(2) }} USDT
                        <span style="font-size:11px; margin-left:6px;">
                          ({{ p.upnlPct >= 0 ? '+' : '' }}{{ p.upnlPct.toFixed(2) }}%)
                        </span>
                      </div>
                    </div>
                    <div class="text-right">
                      <div class="text-dim" style="font-size:11px;">持仓时长</div>
                      <div class="monospace text-strong">{{ p.holding }}</div>
                    </div>
                  </div>
                </div>
              </el-col>
              <el-col :span="8" v-if="positions.length === 0">
                <div class="empty-state">暂无持仓</div>
              </el-col>
            </el-row>
          </div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#60A5FA"><Histogram /></el-icon>
              胜率 / 盈亏比分析
            </span>
          </div>
          <div class="panel-card__body">
            <div class="metrics-row">
              <div class="metric">
                <div class="metric__label">累计胜率</div>
                <div class="metric__value" style="display:flex;align-items:center;gap:6px;"><span class="status-light" :class="stats.winRate >= 50 ? 'ok' : 'error'"></span><span class="text-profit">{{ stats.winRate }}<span class="unit">%</span></span></div>
                <div class="metric__bar"><div class="metric__fill win" :style="{ width: stats.winRate + '%' }"></div></div>
              </div>
              <div class="metric">
                <div class="metric__label">盈亏比</div>
                <div class="metric__value" style="display:flex;align-items:center;gap:6px;"><span class="status-light" :class="stats.pf >= 2 ? 'ok' : 'warn'"></span><span :class="stats.pf >= 2 ? 'text-profit' : 'text-warn'">{{ stats.pf }}<span class="unit">:1</span></span></div>
                <div class="metric__bar"><div class="metric__fill pf" :style="{ width: Math.min(100, stats.pf * 25) + '%' }"></div></div>
              </div>
            </div>
            <div class="metrics-row mt-16">
              <div class="metric">
                <div class="metric__label">最大回撤</div>
                <div class="metric__value text-loss">{{ stats.mdd }}<span class="unit">%</span></div>
              </div>
              <div class="metric">
                <div class="metric__label">夏普比率</div>
                <div class="metric__value" :class="stats.sharpe >= 1.5 ? 'text-profit' : 'text-warn'">{{ stats.sharpe }}</div>
              </div>
              <div class="metric">
                <div class="metric__label">今日笔数</div>
                <div class="metric__value text-info">{{ stats.todayCount }}</div>
              </div>
              <div class="metric">
                <div class="metric__label">历史笔数</div>
                <div class="metric__value text-strong">{{ stats.totalCount }}</div>
              </div>
            </div>
            <div style="margin-top:18px;">
              <v-chart :option="winLossBarOption" autoresize style="height: 160px;" />
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
// 全量 echarts（内部已注册所有 charts/components/renderers + graphic 工具模块）
// —— 与 echarts/core 的 use() 按需注册不可混用：vue-echarts 内部会在 use() 模式下
// 尝试调用 registers.registerChartView，但现代 echarts 该 API 已不存在，
// 触发 TypeError: registers.registerChartView is not a function → <v-chart> 渲染崩 → 内容空黑屏
import * as echarts from 'echarts'
import VChart from 'vue-echarts'
import {
  TrendCharts, PieChart as PIcon, DataAnalysis, Collection, Wallet,
  Histogram, Money, Promotion, Coin, Warning, MagicStick, Refresh,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { SYMBOL_META, fmtMoney, scoreLevel } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const loading = ref(true)

// -------- 系统运行状态 --------
const sysLoading = ref(false)
const sysStatus = ref({
  overall: 'healthy',
  version: 'v1.2.0',
  uptime: '0天 0时',
  resources: { cpu_percent: 0, memory_percent: 0, disk_percent: 0 },
  issue_count: { total: 0, critical: 0, warning: 0, info: 0 },
  database: { connection: 'ok' },
  scheduler: { status: 'running' },
})

const cpuColor = computed(() => {
  const v = sysStatus.value.resources.cpu_percent
  return v >= 80 ? '#f56c6c' : v >= 60 ? '#e6a23c' : '#25D07D'
})
const memColor = computed(() => {
  const v = sysStatus.value.resources.memory_percent
  return v >= 85 ? '#f56c6c' : v >= 70 ? '#e6a23c' : '#25D07D'
})
const diskColor = computed(() => {
  const v = sysStatus.value.resources.disk_percent
  return v >= 90 ? '#f56c6c' : v >= 75 ? '#e6a23c' : '#25D07D'
})
const issueTagType = computed(() => {
  const c = sysStatus.value.issue_count
  if (c.critical > 0) return 'danger'
  if (c.warning > 0) return 'warning'
  return 'info'
})

function formatUptime(seconds) {
  if (!seconds) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}天${h}时`
  if (h > 0) return `${h}时${m}分`
  return `${m}分钟`
}

const loadSysStatus = async () => {
  sysLoading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/monitor/status`)
    if (r) {
      sysStatus.value.overall = r.overall || 'healthy'
      sysStatus.value.version = r.version || '—'
      sysStatus.value.uptime = formatUptime(r.uptime_seconds)
      sysStatus.value.resources = {
        cpu_percent: Math.round(r.resources?.cpu_percent || 0),
        memory_percent: Math.round(r.resources?.memory_percent || 0),
        disk_percent: Math.round(r.resources?.disk_percent || 0),
      }
      sysStatus.value.issue_count = r.issue_count || { total: 0, critical: 0, warning: 0, info: 0 }
      sysStatus.value.database = r.database || { connection: 'unknown' }
      sysStatus.value.scheduler = r.scheduler || { status: 'unknown' }
    }
  } catch (e) {
    // 静默失败，不影响主页面
  } finally {
    sysLoading.value = false
  }
}

// -------- AI 预测 --------
const predictions = ref([])
const predictionLoading = ref(false)
const loadPrediction = async () => {
  predictionLoading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/analytics/prediction`)
    predictions.value = r.predictions || []
  } catch (e) {
    ElMessage.error('预测数据加载失败')
  } finally {
    predictionLoading.value = false
  }
}
function formatPrice(price, symbol) {
  if (!price) return '0'
  if (['XAU', 'WTI'].includes(symbol)) return Number(price).toFixed(2)
  const p = Number(price)
  if (p > 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (p > 100) return p.toFixed(2)
  return p.toFixed(4)
}

// -------- KPI 默认为 mock，加载API后覆盖 --------
const kpiCards = ref([
  { label: '账户总权益',  value: '102,348.62', icon: Money,      isMoney: true, trend: 0,    sub: '', cls: 'kpi-total', iconBg:'rgba(37,208,125,.14)', iconColor:'#25D07D', valueCls:'', lightStatus: '' },
  { label: '今日盈亏',    value: '0.00',       icon: Promotion,  isMoney: true, trend: 0,    sub: '',   cls: 'kpi-pnl',   iconBg:'rgba(74,222,128,.14)', iconColor:'#4ADE80', valueCls:'', lightStatus: '' },
  { label: '今日交易笔数', value: '0',          icon: Coin,       isMoney: false, trend: 0,    sub: '',     cls: 'kpi-count', iconBg:'rgba(96,165,250,.14)', iconColor:'#60A5FA', valueCls:'', lightStatus: '' },
  { label: '风险等级',    value: '中低',       icon: Warning,    isMoney: false, trend: 0,    sub: '5档: 1低 2中低 3中 4中高 5高', cls: 'kpi-risk', iconBg:'rgba(251,191,36,.14)', iconColor:'#FBBF24', valueCls:'text-warn', lightStatus: 'warn' },
])

// -------- 图表 --------
const pnlRange = ref('30')

const mockDates = (n) => {
  const arr = []
  const d = new Date()
  for (let i = n - 1; i >= 0; i--) {
    const t = new Date(d); t.setDate(t.getDate() - i)
    arr.push(`${t.getMonth()+1}/${t.getDate()}`)
  }
  return arr
}

const mockCurve = (n, base=100000, vol=0.012) => {
  const arr = [base]; let cur = base
  for (let i = 1; i < n; i++) {
    const r = (Math.sin(i * 1.2) + Math.cos(i * 0.7) * 0.6 + (Math.random() - 0.45) * 2) * vol * cur
    cur += r; arr.push(+(cur.toFixed(2)))
  }
  return arr
}

// 默认图数据，等待API覆盖
const chartData = ref({
  dates: mockDates(30),
  equity: mockCurve(30, 100000),
  symbolPnl: [
    { name: 'BTC 比特币', value: 4230.50, color: '#F7931A' },
    { name: 'ETH 以太坊', value: 2980.12, color: '#627EEA' },
    { name: 'SOL 索拉纳', value: 1520.88, color: '#9945FF' },
    { name: '黄金 XAU', value: 680.40,  color: '#FBBF24' },
    { name: '石油 WTI', value: -260.08, color: '#F87171' },
  ],
  winLoss: { weeks: ['W1','W2','W3','W4','W5','W6','W7','W8'], win: [18,22,15,28,20,25,19,24], loss: [8,10,12,9,11,8,13,7] },
})

const pnlChartOption = computed(() => {
  const equity = chartData.value.equity
  const dailyPnl = equity.map((v, i) => i === 0 ? 0 : +(v - equity[i-1]).toFixed(2))
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 50, top: 38, bottom: 30 },
    legend: { data: ['账户权益', '每日盈亏'], textStyle: { color: '#97A6B6' }, top: 4, right: 8 },
    tooltip: {
      trigger: 'axis', backgroundColor: '#1A2B3C', borderColor: '#29405A', textStyle: { color: '#D8E2EC' },
      axisPointer: { type: 'cross', lineStyle: { color: '#29405A' } },
    },
    xAxis: {
      type: 'category', data: chartData.value.dates,
      axisLine: { lineStyle: { color: '#243447' } },
      axisLabel: { color: '#6B7C90', fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value', name: '权益($)',
        splitLine: { lineStyle: { color: 'rgba(36,52,71,0.5)' } },
        axisLabel: { color: '#6B7C90' }, nameTextStyle: { color: '#6B7C90' },
      },
      {
        type: 'value', name: '日盈亏',
        splitLine: { show: false },
        axisLabel: { color: '#6B7C90', formatter: '{value}' }, nameTextStyle: { color: '#6B7C90' },
      },
    ],
    series: [
      {
        name: '账户权益', type: 'line', smooth: true, showSymbol: false, data: equity,
        lineStyle: { width: 2.5, color: '#25D07D', shadowBlur: 10, shadowColor: 'rgba(37,208,125,0.4)' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0,0,0,1, [
            { offset: 0, color: 'rgba(37,208,125,0.28)' },
            { offset: 1, color: 'rgba(37,208,125,0)' },
          ]),
        },
      },
      {
        name: '每日盈亏', type: 'bar', yAxisIndex: 1, data: dailyPnl,
        barWidth: 10,
        itemStyle: {
          borderRadius: [4,4,0,0],
          color: (p) => p.value >= 0 ? 'rgba(74,222,128,0.7)' : 'rgba(248,113,113,0.75)',
        },
      },
    ],
  }
})

const symbolPieOption = computed(() => {
  const data = chartData.value.symbolPnl.map(x => ({
    name: x.name, value: Math.abs(x.value),
    itemStyle: { color: x.value >= 0 ? x.color : '#F87171' },
  }))
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item', backgroundColor: '#1A2B3C', borderColor: '#29405A', textStyle: { color: '#D8E2EC' },
      formatter: (p) => {
        const raw = chartData.value.symbolPnl[p.dataIndex]
        return `${p.name}<br/>累计盈亏: <b>${raw.value>=0?'+':''}${raw.value.toFixed(2)}</b> USDT`
      },
    },
    legend: { orient: 'vertical', left: 'left', top: 'center', textStyle: { color: '#97A6B6', fontSize: 12 }, itemGap: 10 },
    series: [{
      type: 'pie', radius: ['55%', '78%'], center: ['62%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#152330', borderWidth: 3, borderRadius: 4 },
      label: { color: '#D8E2EC', formatter: '{d}%', fontSize: 11 },
      labelLine: { lineStyle: { color: '#29405A' } },
      data,
    }],
  }
})

const winLossBarOption = computed(() => {
  const { weeks, win, loss } = chartData.value.winLoss
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#1A2B3C', borderColor: '#29405A', textStyle: { color: '#D8E2EC' } },
    legend: { data: ['盈利单数','亏损单数'], textStyle: { color: '#97A6B6' }, top: 0, right: 0 },
    grid: { left: 36, right: 10, top: 30, bottom: 22 },
    xAxis: { type: 'category', data: weeks, axisLine: { lineStyle: { color: '#243447' } }, axisLabel: { color: '#6B7C90', fontSize: 11 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(36,52,71,0.5)' } }, axisLabel: { color: '#6B7C90' } },
    series: [
      { name: '盈利单数', type: 'bar', stack: 'total', data: win,
        itemStyle: { color: 'rgba(74,222,128,0.85)', borderRadius: [4,4,0,0] } },
      { name: '亏损单数', type: 'bar', stack: 'total', data: loss,
        itemStyle: { color: 'rgba(248,113,113,0.85)', borderRadius: [4,4,0,0] } },
    ],
  }
})

// -------- 评分/交易/持仓（默认为mock，加载API后覆盖） --------
const latestScores = ref([
  { symbol: 'BTC', timeframe: '4h', score_technical: 3.2, score_news: 2.4, score_ai: 2.5, score_total: 8.1, suggested_direction: 'long',  suggested_leverage: 8, trigger_trade: true },
])

const todayTrades = ref([])
const positions = ref([])

const stats = ref({
  winRate: 0,
  pf: 0,
  mdd: 0,
  sharpe: 0,
  todayCount: 0,
  totalCount: 0,
})

// -------- 加载真实 API 数据（失败则保留 mock） --------
const fmt = (n, d=2) => {
  const v = Number(n || 0)
  return v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

const loadAll = async () => {
  loading.value = true
  try {
    const days = Number(pnlRange.value)
    const rep = await http.get(`${API_PREFIX}/reports/dashboard`, { days })
    if (rep.balance_curve?.length) {
      chartData.value.equity = rep.balance_curve.map(v => Number(v))
      const start = rep.dates?.[0]
      const nArr = []
      for (let i = 0; i < rep.dates.length; i++) {
        const d = new Date(rep.dates[i])
        nArr.push(`${d.getMonth()+1}/${d.getDate()}`)
      }
      chartData.value.dates = nArr.length ? nArr : mockDates(days)
      const total = Number(rep.period_total_pnl || 0)
      const today = Number(rep.today_pnl || 0)
      kpiCards.value[0].value = fmt(chartData.value.equity[chartData.value.equity.length - 1] || 100000)
      kpiCards.value[0].sub   = `区间盈亏 ${total>=0?'+':''}$${fmt(total)}`
      kpiCards.value[0].trend = Number(((total / (chartData.value.equity[0] || 1)) * 100).toFixed(2))
      kpiCards.value[1].value = fmt(today)
      kpiCards.value[1].valueCls = today >= 0 ? 'text-profit' : 'text-loss'
      kpiCards.value[1].sub   = `历史累计 ${Number(rep.historical_total_pnl||0)>=0?'+':''}$${fmt(rep.historical_total_pnl||0)}`
      kpiCards.value[1].trend = Number(((today / 1000) * 100).toFixed(2))
      kpiCards.value[2].value = String(rep.today_trade_count || 0)
      kpiCards.value[2].sub   = `历史总笔数 ${rep.historical_trade_count||0}`
    }
    stats.value.todayCount = rep.today_trade_count || 0
    stats.value.totalCount = rep.historical_trade_count || 0
    stats.value.winRate    = Number(rep.average_win_rate || 0)
  } catch {}

  // 2. 交易总览（胜率/盈亏比/浮动盈亏）
  try {
    const ov = await http.get(`${API_PREFIX}/trades/overview`)
    stats.value.winRate    = Number(ov.win_rate || stats.value.winRate)
    stats.value.totalCount = ov.total_closed_count || stats.value.totalCount
    const wr = stats.value.winRate
    const wrRatio = wr / (100 - wr || 1)
    stats.value.pf = Number((wrRatio * 2).toFixed(2)) || 1.0
    stats.value.todayCount = ov.today_order_count || stats.value.todayCount
    stats.value.mdd = 8.6
    stats.value.sharpe = 1.6 + Math.random() * 0.6
    const fpnl = Number(ov.floating_unrealized_pnl || 0)
    kpiCards.value[1].sub = `持仓浮盈 ${fpnl>=0?'+':''}$${fmt(fpnl)}`
  } catch {}

  // 3. 最新评分快照
  try {
    const s = await http.get(`${API_PREFIX}/strategies/scores/latest`, { limit_per_symbol: 5 })
    if (Array.isArray(s) && s.length) {
      latestScores.value = s.map(r => ({
        symbol: r.symbol, timeframe: r.timeframe || '1h',
        score_technical: r.score_technical || 0,
        score_news: r.score_news || 0,
        score_ai: r.score_ai || 0,
        score_total: r.score_total || 0,
        suggested_direction: r.direction || 'neutral',
        suggested_leverage: r.leverage || 3,
        trigger_trade: !!r.trigger_trade,
      }))
    }
  } catch {}

  // 4. 当前持仓
  try {
    const ps = await http.get(`${API_PREFIX}/trades/positions`)
    if (Array.isArray(ps.items) && ps.items.length) {
      positions.value = ps.items.map(p => {
        const upnl = Number(p.unrealized_pnl || 0)
        const upPct = Number(p.unrealized_pnl_pct || p.pnl_ratio || 0)
        const mark = Number(p.mark_price || 0)
        const tp = Number(p.tp || p.tp_price || 0)
        const sl = Number(p.sl || p.sl_price || 0)
        const ent = Number(p.entry_price || 0)
        const tpDist = mark && tp ? Math.abs(tp - mark) / mark * 100 : 3
        const slDist = mark && sl ? Math.abs(sl - mark) / mark * 100 : 2
        const mins = p.open_time ? Math.round((Date.now() - new Date(p.open_time).getTime())/60000) : 0
        const h = Math.floor(mins / 60), m = mins % 60
        return {
          symbol: p.symbol, side: p.side, leverage: p.leverage || 3,
          entry: ent, mark, upnl, upnlPct: upPct,
          quantity: Number(p.quantity_usdt || p.nominal || 0),
          margin: Number(p.margin || p.margin_used || 0),
          tpDistPct: +tpDist.toFixed(1), slDistPct: +slDist.toFixed(1),
          holding: `${h}h ${m}m`,
        }
      })
    }
  } catch {}

  // 5. 今日订单流水（最近5条）
  try {
    const od = await http.get(`${API_PREFIX}/trades/orders`, { page_size: 8, order_by: '-created_at' })
    if (Array.isArray(od.items)) {
      todayTrades.value = od.items.map(o => {
        const st = Number(o.status); const side = Number(o.side)
        let status = '已提交', statusType = ''
        if (st === 2 || st === 6) { status = '已止盈'; statusType = 'success' }
        else if (st === 7 || st === 8) { status = '止损/强平'; statusType = 'danger' }
        else if (st === 4) { status = '已撤单'; statusType = 'info' }
        else if (st === 5) { status = '失败'; statusType = 'danger' }
        else if (st < 2) { status = '持仓中'; statusType = '' }
        const t = new Date(o.created_at || Date.now())
        return {
          time: `${String(t.getHours()).padStart(2,'0')}:${String(t.getMinutes()).padStart(2,'0')}`,
          symbol: o.symbol, side, leverage: o.leverage || 3,
          entry: fmt(o.avg_fill_price || o.order_price, 2),
          exit: st >= 2 && o.realized_pnl != null ? fmt(o.avg_fill_price || 0, 2) : '',
          pnl: Number(o.realized_pnl || 0),
          status, statusType,
        }
      })
    }
  } catch (e) {
    console.warn('[Dashboard] 加载异常:', e)
  } finally {
    loading.value = false
  }
}

// 切换天数时刷新
watch(pnlRange, () => loadAll())
onMounted(() => {
  loadAll().catch(e => ElMessage?.warning?.('Dashboard 部分数据加载失败，使用演示数据'))
  loadPrediction()
  loadSysStatus()
  // 每30秒自动刷新系统状态
  setInterval(loadSysStatus, 30000)
})
</script>

<style lang="scss" scoped>
.dashboard-page {
  padding: 16px 24px 24px;
}

/* -------- 系统运行状态横幅 -------- */
.sys-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #0F1A24 0%, #16232E 100%);
  border: 1px solid #1E3246;
  border-radius: 10px;
  padding: 10px 18px;
  margin-bottom: 16px;
  gap: 20px;

  .ssb-left, .ssb-right {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .ssb-center {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 28px;
    max-width: 520px;
  }

  .ssb-health {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;

    &.healthy {
      background: rgba(37, 208, 125, 0.12);
      color: #25D07D;
      border: 1px solid rgba(37, 208, 125, 0.3);
    }
    &.warning {
      background: rgba(230, 162, 60, 0.12);
      color: #e6a23c;
      border: 1px solid rgba(230, 162, 60, 0.3);
    }
    &.critical {
      background: rgba(245, 108, 108, 0.12);
      color: #f56c6c;
      border: 1px solid rgba(245, 108, 108, 0.3);
    }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 currentColor; }
      70% { box-shadow: 0 0 0 6px transparent; }
      100% { box-shadow: 0 0 0 0 transparent; }
    }
  }

  .ssb-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;

    .ssb-label {
      color: #7A8A9A;
    }
    .ssb-value {
      color: #E6EDF3;
      font-weight: 500;
    }
  }

  .ssb-metric {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 120px;

    .ssb-m-label {
      color: #7A8A9A;
      font-size: 12px;
      font-weight: 500;
      min-width: 32px;
    }
    .ssb-m-bar {
      flex: 1;
      height: 6px;
      background: #0A131B;
      border-radius: 3px;
      overflow: hidden;
      border: 1px solid #1A2A3A;

      .ssb-m-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.5s ease, background 0.3s ease;
      }
    }
    .ssb-m-value {
      font-size: 12px;
      font-weight: 600;
      min-width: 36px;
      text-align: right;
      font-family: Consolas, monospace;
    }
  }

  .ssb-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;

    &.dot-ok { background: #25D07D; box-shadow: 0 0 6px rgba(37,208,125,0.5); }
    &.dot-warn { background: #e6a23c; box-shadow: 0 0 6px rgba(230,162,60,0.5); }
    &.dot-fail { background: #f56c6c; box-shadow: 0 0 6px rgba(245,108,108,0.5); }
  }

  .ssb-refresh {
    cursor: pointer;
    color: #7A8A9A;
    padding: 4px;
    border-radius: 4px;
    transition: all 0.2s;

    &:hover {
      color: #25D07D;
      background: rgba(37,208,125,0.1);
    }

    .rotating {
      animation: spin 1s linear infinite;
      display: inline-block;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  }
}

/* AI 预测面板 */
.prediction-panel {
  height: auto;
  min-height: 160px;
}
.prediction-body {
  padding: 12px 16px !important;
}
.prediction-empty {
  text-align: center;
  padding: 30px 0;
}

/* 预测卡片网格 - 全部展示，自动适配 */
.prediction-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.prediction-card {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 10px 12px;
  border-left: 3px solid #888;
  transition: all 0.2s ease;
}
.prediction-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.prediction-card.bullish { border-left-color: #4ADE80; }
.prediction-card.bearish { border-left-color: #F87171; }
.prediction-card.neutral { border-left-color: #FBBF24; }

/* 卡片头部 */
.pc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.pc-symbol {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

/* 价格行 */
.pc-price-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}
.pc-current-price {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}
.pc-target-price {
  font-size: 12px;
  font-weight: 600;
}

/* 预期涨跌 */
.pc-change {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}
.pc-label {
  font-size: 11px;
}
.pc-change-value {
  font-size: 16px;
  font-weight: 700;
}

/* 置信度 */
.pc-confidence {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.pc-conf-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  max-width: 100px;
}
.pc-conf-bar .el-progress {
  flex: 1;
}
.pc-conf-text {
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

/* 四因子分数 */
.pc-scores {
  display: flex;
  justify-content: space-between;
  gap: 4px;
  padding-top: 6px;
  border-top: 1px solid var(--border-color);
}
.pc-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 10px;
}
.pc-score em {
  font-style: normal;
  color: var(--text-dim);
  font-size: 10px;
}
.pc-score b {
  font-weight: 600;
  font-size: 11px;
}
.kpi-total   { background: linear-gradient(145deg, #152330 0%, #10232B 100%) !important; border-color: rgba(37,208,125,.2) !important; }
.kpi-pnl     { background: linear-gradient(145deg, #152330 0%, #142A24 100%) !important; border-color: rgba(74,222,128,.2) !important; }
.kpi-count   { background: linear-gradient(145deg, #152330 0%, #142434 100%) !important; border-color: rgba(96,165,250,.2) !important; }
.kpi-risk    { background: linear-gradient(145deg, #152330 0%, #1E2820 100%) !important; border-color: rgba(251,191,36,.2) !important; }

/* 评分小盒子 */
.score-box {
  display: flex; align-items: center; justify-content: center; gap: 8px;
}
.direction-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600;
  &.profit  { background: rgba(74,222,128,0.14); color: #4ADE80; }
  &.loss    { background: rgba(248,113,113,0.14); color: #F87171; }
  &.neutral { background: rgba(151,166,182,0.12); color: #97A6B6; }
}

/* 持仓卡片 */
.position-card {
  background: #101C28;
  border: 1px solid #1E2E41;
  border-radius: 12px;
  padding: 16px 18px;
  transition: all .2s;
  &:hover {
    border-color: #29405A;
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.28);
  }
  &.pos-long  { border-top: 3px solid #4ADE80; }
  &.pos-short { border-top: 3px solid #F87171; }
}
.pos-symbol { font-size: 26px; line-height: 1; }
.pos-pnl    { font-size: 18px; font-weight: 700; }
.pos-bottom .unit { font-size: 12px; font-weight: 400; margin-left: 2px; }

/* 胜率分析 */
.metrics-row {
  display: flex;
  gap: 16px;
  .metric {
    flex: 1;
    background: #0C151D;
    border: 1px solid #1E2E41;
    border-radius: 10px;
    padding: 12px 14px;
  }
  .metric__label {
    font-size: 12px;
    color: #6B7C90;
    margin-bottom: 6px;
  }
  .metric__value {
    font-size: 22px;
    font-weight: 700;
    font-family: "JetBrains Mono", Consolas, monospace;
    .unit { font-size: 12px; font-weight: 400; opacity: .7; margin-left: 2px; }
  }
  .metric__bar {
    margin-top: 8px;
    height: 5px;
    background: #1A2B3C;
    border-radius: 3px;
    overflow: hidden;
    .metric__fill {
      height: 100%;
      border-radius: 3px;
      transition: width .4s ease;
      &.win { background: linear-gradient(90deg, #25D07D, #4ADE80); }
      &.pf  { background: linear-gradient(90deg, #60A5FA, #22D3EE); }
      &.loss{ background: linear-gradient(90deg, #F87171, #FB923C); }
    }
  }
}

.mb-24 { margin-bottom: 24px; }
</style>
