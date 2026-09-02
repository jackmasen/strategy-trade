<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Reading /></el-icon>新闻情绪中心</h2>
        <div class="page-subtitle">关键词预筛选 + AI深度分析 · 自动去重 · 节省90%分析成本</div>
      </div>
      <div class="flex gap-12">
        <el-select v-model="symbol" placeholder="关联品种" style="width:140px;" clearable @change="load">
          <el-option label="全部" value="" />
          <el-option v-for="(m,k) in SYMBOL_META" :key="k" :label="k + ' / ' + m.name" :value="k" />
        </el-select>
        <el-select v-model="sentiment" placeholder="情绪" style="width:110px;" clearable @change="load">
          <el-option label="利多" :value="1" />
          <el-option label="中性" :value="0" />
          <el-option label="利空" :value="-1" />
        </el-select>
        <el-select v-model="impactFilter" placeholder="影响级别" style="width:120px;" clearable @change="load">
          <el-option label="全部" :value="''" />
          <el-option label="重大(4)" :value="4" />
          <el-option label="重要(3)" :value="3" />
          <el-option label="一般(2)" :value="2" />
          <el-option label="轻微(1)" :value="1" />
        </el-select>
        <el-input-number v-model="lookback" :min="1" :max="168" :step="6" style="width:130px;" @change="load" />
        <el-button :icon="Refresh" :loading="collecting" @click="collect(true)">采集</el-button>
        <el-button type="warning" :icon="MagicStick" :loading="autoAnalyzing" @click="autoCollectAnalyze">一键采集+AI分析</el-button>
        <el-button type="primary" :icon="Cpu" :loading="aiAnalyzing" @click="aiAnalyze" plain>AI深度分析</el-button>
      </div>
    </div>

    <!-- 情绪汇总 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="5">
        <div class="stat-card">
          <div class="stat-card__label">近 {{ summary.hours || 24 }}h 新闻</div>
          <div class="stat-card__value">{{ summary.total }}</div>
          <div class="stat-card__extra text-muted">
            关键词库: {{ kwStats.total_keywords || 0 }} 个关键词
          </div>
        </div>
      </el-col>
      <el-col :span="5">
        <div class="stat-card">
          <div class="stat-card__label">利多 / 利空 / 中性</div>
          <div class="stat-card__value">
            <span class="text-profit">{{ summary.positive }}</span> /
            <span class="text-loss">{{ summary.negative }}</span> /
            <span class="text-muted">{{ summary.neutral }}</span>
          </div>
          <div class="stat-card__extra">
            利多占比 <b class="text-profit">{{ summary.total ? (summary.positive/summary.total*100).toFixed(0) : 0 }}%</b>
          </div>
        </div>
      </el-col>
      <el-col :span="5">
        <div class="stat-card">
          <div class="stat-card__label">情绪分数(-1~+1)</div>
          <div class="stat-card__value" :class="summary.avg_sentiment_score>=0?'text-profit':'text-loss'">
            {{ (summary.avg_sentiment_score || 0).toFixed(2) }}
          </div>
          <div class="stat-card__extra">
            评分: <b class="text-warn">{{ (summary.news_pnl_score || 0).toFixed(2) }}</b>
            <span class="text-dim"> / 3.0</span>
          </div>
        </div>
      </el-col>
      <el-col :span="5">
        <div class="stat-card">
          <div class="stat-card__label">重大事件(影响≥3)</div>
          <div class="stat-card__value text-warn">{{ summary.hot_count }}</div>
          <div class="stat-card__extra text-warn">
            已AI分析: {{ summary.ai_analyzed || 0 }} 条
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card">
          <div class="stat-card__label">系统状态</div>
          <div class="stat-card__value" style="font-size:14px;">
            <span :class="schedulerRunning ? 'text-profit' : 'text-loss'">●</span>
            {{ schedulerRunning ? '运行中' : '未启动' }}
          </div>
          <div class="stat-card__extra text-muted" style="font-size:11px;">
            采集30min / AI 2h / 清理3:00
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 关键词库统计 -->
    <div class="panel-card mb-16" v-if="kwStats.categories">
      <div class="panel-card__header">
        <span class="panel-card__title">关键词预筛选引擎</span>
        <el-tag type="success" effect="dark" size="small">成本优化：仅影响≥3的新闻调AI</el-tag>
      </div>
      <div class="panel-card__body" style="padding:12px 20px;">
        <div class="kw-categories">
          <div v-for="(info, cat) in kwStats.categories" :key="cat" class="kw-category-item">
            <span class="kw-cat-name">{{ categoryName(String(cat)) }}</span>
            <span class="kw-cat-count">{{ info.count }}词</span>
            <span class="kw-cat-impact" :class="info.max_impact >= 4 ? 'text-loss' : info.max_impact >= 3 ? 'text-warn' : 'text-muted'">
              L{{ info.max_impact }}
            </span>
            <div class="kw-cat-symbols">
              <el-tag v-for="s in info.symbols" :key="s" size="small" effect="plain" style="margin:1px;">{{ s }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 自动化流程结果 -->
    <el-alert
      v-if="lastAutoResult"
      :title="`一键流程完成 · 耗时 ${lastAutoResult.elapsed_seconds}s`"
      type="success"
      :closable="true"
      @close="lastAutoResult = null"
      style="margin-bottom: 16px;"
    >
      <template #default>
        <div style="font-size:13px; line-height:1.8;">
          <b>采集</b>: 抓取 {{ lastAutoResult.crawl.fetched }} 条, 新增 {{ lastAutoResult.crawl.inserted }} 条, 去重跳过 {{ lastAutoResult.crawl.skipped_dup }} 条<br/>
          <b>AI预筛选</b>: 扫描 {{ lastAutoResult.ai_analysis.total_scanned }} 条 →
          需分析 {{ lastAutoResult.ai_analysis.total }} 条,
          已分析 {{ lastAutoResult.ai_analysis.analyzed }} 条,
          失败 {{ lastAutoResult.ai_analysis.failed }} 条,
          跳过已分析 {{ lastAutoResult.ai_analysis.skipped_already_analyzed }} 条,
          跳过非重要 {{ lastAutoResult.ai_analysis.skipped_not_important }} 条
        </div>
      </template>
    </el-alert>

    <div class="panel-card">
      <div class="panel-card__header">
        <span class="panel-card__title">新闻列表</span>
        <div class="flex gap-8" style="align-items:center;">
          <el-tag v-if="aiAnalyzing" type="warning" effect="dark" size="small">
            <el-icon class="is-loading"><Loading /></el-icon> AI分析中...
          </el-tag>
          <span class="text-dim" style="font-size: 12px;">
            <span v-if="meta">共 {{ meta.total }} 条 · 第 {{ page }} / {{ Math.max(1, Math.ceil(meta.total / pageSize)) }} 页</span>
            <span v-else>加载中...</span>
          </span>
        </div>
      </div>
      <div class="panel-card__body" style="padding: 0;">
        <el-table :data="rows" v-loading="loading" :header-cell-style="{ background:'#192738' }">
          <el-table-column label="发布时间" width="145">
            <template #default="{ row }">{{ fmtTime(row.published_at) }}</template>
          </el-table-column>
          <el-table-column label="来源" width="120">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="sourceType(row.source)">
                {{ sourceName(row.source) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="影响" width="100" align="center">
            <template #default="{ row }">
              <span v-for="i in 4" :key="i" class="impact-bar" :class="{ active: i <= row.impact_level }"></span>
              <div class="text-dim" style="font-size: 11px; margin-top: 2px;">L{{ row.impact_level }}/4</div>
            </template>
          </el-table-column>
          <el-table-column label="标题/摘要" min-width="380">
            <template #default="{ row }">
              <div class="flex gap-8" style="align-items:center;">
                <el-tag v-if="row.is_hot" size="small" type="danger" effect="dark">HOT</el-tag>
                <el-tag v-if="row.is_hot && row.analyzed_at" size="small" type="success" effect="dark">AI</el-tag>
                <a v-if="row.url" :href="row.url" target="_blank" class="news-title">{{ row.title }}</a>
                <span v-else class="text-strong">{{ row.title }}</span>
              </div>
              <div class="text-dim" style="margin-top:4px; font-size:12px;">{{ row.summary }}</div>
              <div v-if="row.sentiment_keywords?.length" class="mt-4">
                <el-tag v-for="k in row.sentiment_keywords.slice(0,6)" :key="k"
                  size="small" type="info" effect="plain" style="margin-right:4px;">{{ k }}</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="品种" width="180">
            <template #default="{ row }">
              <el-tag v-for="s in row.related_symbols" :key="s" size="small" effect="dark"
                :style="{ borderColor: SYMBOL_META[s]?.color, color: SYMBOL_META[s]?.color, background: 'transparent', margin:'1px' }">
                {{ SYMBOL_META[s]?.icon || '●' }} {{ s }}
              </el-tag>
              <span v-if="!row.related_symbols?.length" class="text-dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="情绪" width="120" align="center">
            <template #default="{ row }">
              <span class="pnl-badge" :class="row.sentiment===1?'profit':row.sentiment===-1?'loss':'neutral'">
                {{ row.sentiment===1?'利多':row.sentiment===-1?'利空':'中性' }}
              </span>
              <div class="text-dim" style="font-size:11px; margin-top:4px;">
                {{ Number(row.sentiment_score).toFixed(2) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分类" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ categoryName(row.category) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="panel-card__body" v-if="meta && meta.total > pageSize"
        style="border-top: 1px solid #1E2E41; padding: 14px 20px; display: flex; justify-content: flex-end;">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="meta.total"
          :page-sizes="[15, 30, 50, 100]" layout="total, sizes, prev, pager, next, jumper" background @change="load" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Reading, Refresh, MagicStick, Cpu, Loading } from '@element-plus/icons-vue'
import { SYMBOL_META, NEWS_SOURCE_META } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const symbol = ref('')
const sentiment = ref(null)
const impactFilter = ref(null)
const lookback = ref(24)
const page = ref(1)
const pageSize = ref(30)
const loading = ref(false)
const collecting = ref(false)
const autoAnalyzing = ref(false)
const aiAnalyzing = ref(false)
const schedulerRunning = ref(false)
const lastAutoResult = ref(null)
const kwStats = ref({})
const summary = ref({ total: 0, positive: 0, negative: 0, neutral: 0,
                     avg_sentiment_score: 0, news_pnl_score: 0, hot_count: 0, ai_analyzed: 0, hours: 24 })
const rows = ref([])
const meta = ref(null)

const sourceName = (s) => NEWS_SOURCE_META[s]?.name || NEWS_SOURCE_META[99]?.name || '未知'
const sourceType = (s) => {
  const t = NEWS_SOURCE_META[s]?.type
  return t === 'official' ? 'warning' : t === 'crypto' ? 'success' : t === 'energy' ? '' : 'info'
}
const CATEGORY_NAME = {
  macro: '宏观', regulation: '监管', energy: '能源', metals: '金属',
  crypto: '加密', exchange: '交易所', official: '官方', general: '综合',
  markets: '市场', geopolitics: '地缘', sentiment: '情绪', mixed: '综合',
  '': '综合',
}
const categoryName = (c) => CATEGORY_NAME[c] || c || '综合'
const fmtTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  if (isNaN(d.getTime())) return String(t).slice(0, 16)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const collect = async (showMsg = true) => {
  collecting.value = true
  try {
    const r = await http.post(`${API_PREFIX}/news/collect`, null, {
      params: { lookback_hours: Math.max(1, lookback.value) }
    })
    if (showMsg) {
      ElMessage.success(`采集完成 · 抓取 ${r.fetched} 新增 ${r.inserted} 跳过 ${r.skipped_dup} · 耗时 ${r.elapsed_seconds||0}s`)
    }
    await load()
  } catch (e) { /* 拦截器已处理 */ } finally {
    collecting.value = false
  }
}

const autoCollectAnalyze = async () => {
  autoAnalyzing.value = true
  try {
    const r = await http.post(`${API_PREFIX}/news/auto-collect`)
    lastAutoResult.value = r
    ElMessage.success(`采集${r.crawl.inserted}条，AI分析${r.ai_analysis.analyzed}条，耗时${r.elapsed_seconds}s`)
    await load()
    await loadKwStats()
  } catch (e) { /* 拦截器已处理 */ } finally {
    autoAnalyzing.value = false
  }
}

const aiAnalyze = async () => {
  aiAnalyzing.value = true
  try {
    const r = await http.post(`${API_PREFIX}/news/ai-analyze`, null, {
      params: { hours: Math.max(1, lookback.value), limit: 20 }
    })
    ElMessage.success(`AI分析完成：${r.analyzed}/${r.total} 条已分析，跳过已分析${r.skipped_already_analyzed}条，非重要${r.skipped_not_important}条`)
    await load()
  } catch (e) { /* 拦截器已处理 */ } finally {
    aiAnalyzing.value = false
  }
}

const loadKwStats = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/news/keywords/stats`)
    kwStats.value = r
  } catch {}
}

const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/news/sentiment/summary`, {
      symbol: symbol.value, hours: Math.max(1, lookback.value)
    })
    summary.value = {
      total: r.total || 0,
      positive: r.positive || 0,
      negative: r.negative || 0,
      neutral: r.neutral || 0,
      avg_sentiment_score: Number(r.avg_sentiment_score || 0),
      news_pnl_score: Number(r.news_pnl_score || 0),
      hot_count: 0,
      ai_analyzed: 0,
      hours: r.hours || lookback.value,
    }
  } catch (e) { /* mock 兜底 */ }

  try {
    const params = {
      related_symbol: symbol.value || '',
      sentiment: sentiment.value ?? undefined,
      page: page.value, page_size: pageSize.value,
    }
    if (impactFilter.value !== null) params.impact = impactFilter.value
    const r = await http.get(`${API_PREFIX}/news`, params)
    rows.value = (r.items || r.data || []).map(x => x)
    meta.value = { total: r.total || rows.value.length, page: r.page, page_size: r.page_size }
    // 从列表统计 hot_count 和 ai_analyzed
    summary.value.hot_count = rows.value.filter(x => x.impact_level >= 3).length
    summary.value.ai_analyzed = rows.value.filter(x => x.is_hot && x.analyzed_at).length
  } catch (e) { /* 空兜底 */ }
  loading.value = false
}

const loadSchedulerStatus = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/news/status`, {}, { _silent: true })
    schedulerRunning.value = r.running || false
  } catch { /* 空兜底 */ }
}

onMounted(async () => {
  await Promise.all([loadKwStats(), load(), loadSchedulerStatus()])
})
</script>

<style lang="scss" scoped>
.impact-bar {
  display: inline-block;
  width: 14px; height: 6px;
  background: #1E2E41;
  border-radius: 2px;
  margin-right: 2px;
  &.active { background: linear-gradient(90deg, #F87171, #FBBF24); }
}
.news-title {
  color: #D8E2EC;
  text-decoration: none;
  font-weight: 600;
  &:hover { color: #60A5FA; text-decoration: underline; }
}
.mt-4 { margin-top: 4px; }
.kw-categories {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.kw-category-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(30, 46, 65, 0.5);
  border-radius: 6px;
  border: 1px solid #1E2E41;
}
.kw-cat-name { font-weight: 600; font-size: 13px; color: #D8E2EC; }
.kw-cat-count { font-size: 11px; color: #6B7E94; }
.kw-cat-impact { font-size: 11px; font-weight: 700; }
.kw-cat-symbols { display: flex; gap: 2px; flex-wrap: wrap; }
</style>
