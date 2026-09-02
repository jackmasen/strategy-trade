<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><DataAnalysis /></el-icon>策略管理</h2>
        <div class="page-subtitle">配置评分权重、交易品种、杠杆、止盈止损、风控参数</div>
      </div>
      <div class="flex gap-8">
        <el-button :icon="MagicStick" @click="applyTemplate" :loading="tplLoading">一键应用推荐模板</el-button>
        <el-button type="primary" :icon="Plus" size="large" @click="openForm()">新建策略</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="f.is_active" placeholder="启用状态" clearable style="width:140px;">
        <el-option :value="true" label="启用中" />
        <el-option :value="false" label="已停用" />
      </el-select>
      <el-select v-model="f.run_mode" placeholder="运行模式" clearable style="width:160px;">
        <el-option :value="3" label="模拟盘" />
        <el-option :value="2" label="半自动" />
        <el-option :value="1" label="全自动" />
      </el-select>
      <el-input v-model="f.keyword" placeholder="搜索策略名称" clearable style="width:220px;" :prefix-icon="Search" />
      <el-button :icon="RefreshRight" @click="load">刷新</el-button>
    </div>

    <div class="panel-card">
      <el-table :data="rows" v-loading="loading" :header-cell-style="{ background:'#192738' }">
        <el-table-column prop="strategy_name" label="策略" width="200">
          <template #default="{ row }">
            <div class="flex gap-8">
              <el-tag :type="row.is_active ? 'success' : 'info'" effect="dark" round size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
              <span class="text-strong">{{ row.strategy_name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="品种" width="220">
          <template #default="{ row }">
            <el-tag v-for="s in (row.symbols || [])" :key="s" size="small" effect="dark" style="margin-right:4px;">
              {{ SYMBOL_META[s]?.icon }} {{ s }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="周期/方向/模式" width="220">
          <template #default="{ row }">
            <span class="text-dim">{{ row.timeframe }}</span> ·
            <span :class="row.direction_mode===1?'text-profit':row.direction_mode===2?'text-loss':''">
              {{ ['多空都做','只做多','只做空'][row.direction_mode] }}
            </span> ·
            <el-tag size="small" effect="dark" :type="['success','warning','info'][row.run_mode-1]">
              {{ ['全自动','半自动','模拟盘'][row.run_mode-1] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="评分阈值" width="120" align="center">
          <template #default="{ row }">
            <span class="monospace text-warn">≥{{ row.score_threshold }}</span> / 10
          </template>
        </el-table-column>
        <el-table-column label="权重(技/新/AI)" width="150" align="center">
          <template #default="{ row }">
            <span class="monospace">{{ (row.weight_technical*10).toFixed(0) }}/{{ (row.weight_news*10).toFixed(0) }}/{{ (row.weight_ai*10).toFixed(0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="杠杆/盈亏比" width="170" align="center">
          <template #default="{ row }">
            <span class="monospace text-info">{{ row.leverage_mode===1?row.leverage_fixed+'x 固定':'动态' }}</span> ·
            TP:SL = <span class="monospace text-profit">{{ (row.tp_ratio/row.sl_ratio).toFixed(1) }}:1</span>
          </template>
        </el-table-column>
        <el-table-column label="总仓位上限" width="120" align="center">
          <template #default="{ row }">
            <span class="monospace">{{ row.total_position_ratio }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="日最大亏损" width="120" align="center">
          <template #default="{ row }">
            <span class="text-loss">{{ row.daily_max_loss }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" @change="toggle(row)" style="margin-right:10px;" />
            <el-button link type="primary" size="small" :icon="Edit" @click="openForm(row)">编辑</el-button>
            <el-button link type="success" size="small" :icon="View" @click="openDiag(row)">评分诊断</el-button>
            <el-button link type="warning" size="small" :icon="Promotion" @click="runNow(row)">执行</el-button>
            <el-button link type="danger" size="small" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 策略创建/编辑对话框 -->
    <el-dialog
      v-model="formVisible"
      :title="form.id ? '编辑策略' : '新建策略'"
      width="860px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="140px">
        <el-divider content-position="left">基础信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="16">
            <el-form-item label="策略名称" prop="strategy_name">
              <el-input v-model="form.strategy_name" placeholder="如：BTC/ETH 智能跟随 1H/4H" maxlength="60" show-word-limit />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="运行模式" prop="run_mode">
              <el-select v-model="form.run_mode" style="width:100%;">
                <el-option :value="3" label="3-模拟盘（推荐，不下真实单）" />
                <el-option :value="2" label="2-半自动（触发后手动确认）" />
                <el-option :value="1" label="1-全自动（评分达标即下单，慎用）" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="策略描述">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
        <el-form-item label="启用品种" prop="symbols">
          <el-checkbox-group v-model="form.symbols">
            <el-checkbox v-for="(m,k) in SYMBOL_META" :key="k" :label="k" border>
              {{ m.icon }} {{ k }} {{ m.name }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-divider content-position="left">交易时间与方向</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="K线周期" prop="timeframe">
              <el-select v-model="form.timeframe" style="width:100%;">
                <el-option value="1h" label="仅 1 小时" />
                <el-option value="4h" label="仅 4 小时" />
                <el-option value="1h,4h" label="1H + 4H（推荐）" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交易方向" prop="direction_mode">
              <el-radio-group v-model="form.direction_mode">
                <el-radio :value="0">多空都做</el-radio>
                <el-radio :value="1">只做多</el-radio>
                <el-radio :value="2">只做空</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">评分阈值与权重（满分10）</el-divider>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="开仓阈值分" prop="score_threshold">
              <el-input-number v-model="form.score_threshold" :min="0" :max="10" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="强信号阈值" prop="strong_score_threshold">
              <el-input-number v-model="form.strong_score_threshold" :min="0" :max="10" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="权重校验">
              <el-tag :type="Math.abs(form.weight_technical + form.weight_news + form.weight_ai - 1) < 0.01 ? 'success' : 'danger'" effect="dark">
                和 = {{ (form.weight_technical + form.weight_news + form.weight_ai).toFixed(2) }}
                {{ Math.abs(form.weight_technical + form.weight_news + form.weight_ai - 1) < 0.01 ? '✓' : '必须 = 1.0' }}
              </el-tag>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="技术指标权重" prop="weight_technical">
              <el-slider v-model="form.weight_technical" :min="0" :max="1" :step="0.05" show-input />
              <div class="text-dim" style="font-size:12px;">建议范围 0.3 ~ 0.5（默认 0.4）</div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="新闻情绪权重" prop="weight_news">
              <el-slider v-model="form.weight_news" :min="0" :max="1" :step="0.05" show-input />
              <div class="text-dim" style="font-size:12px;">建议范围 0.2 ~ 0.4（默认 0.3）</div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="AI 分析权重" prop="weight_ai">
              <el-slider v-model="form.weight_ai" :min="0" :max="1" :step="0.05" show-input />
              <div class="text-dim" style="font-size:12px;">建议范围 0.2 ~ 0.4（默认 0.3）</div>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">杠杆与止盈止损</el-divider>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="杠杆模式" prop="leverage_mode">
              <el-radio-group v-model="form.leverage_mode">
                <el-radio :value="1">固定</el-radio>
                <el-radio :value="2">动态（推荐）</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="8" v-if="form.leverage_mode === 1">
            <el-form-item label="固定杠杆倍数" prop="leverage_fixed">
              <el-input-number v-model="form.leverage_fixed" :min="3" :max="10" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8" v-else>
            <el-form-item label="低/中/高分杠杆">
              <div class="flex gap-6">
                <el-input-number v-model="form.leverage_low_score" :min="3" :max="10" placeholder="低分" />
                <el-input-number v-model="form.leverage_mid_score" :min="3" :max="10" placeholder="中分" />
                <el-input-number v-model="form.leverage_high_score" :min="3" :max="10" placeholder="高分" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="使用交易所TP/SL" prop="use_exchange_tpsl">
              <el-switch v-model="form.use_exchange_tpsl" />
              <div class="text-dim" style="font-size:12px;">推荐开启（服务器宕机也能触发）</div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="止盈比例 (%)" prop="tp_ratio">
              <el-input-number v-model="form.tp_ratio" :min="0.5" :max="50" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="止损比例 (%)" prop="sl_ratio">
              <el-input-number v-model="form.sl_ratio" :min="0.3" :max="30" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="TP : SL">
              <el-tag :type="(form.tp_ratio/form.sl_ratio) >= 2 ? 'success' : 'warning'" effect="dark">
                {{ (form.tp_ratio/form.sl_ratio).toFixed(2) }} : 1
                {{ (form.tp_ratio/form.sl_ratio) >= 2 ? ' 合格' : ' 建议 ≥ 2:1' }}
              </el-tag>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">仓位管理与风控</el-divider>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="单笔仓位 (%)" prop="single_position_ratio">
              <el-input-number v-model="form.single_position_ratio" :min="1" :max="50" style="width:100%;" />
              <div class="text-dim" style="font-size:12px;">单笔占账户权益比例</div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="总仓位上限 (%)" prop="total_position_ratio">
              <el-input-number v-model="form.total_position_ratio" :min="5" :max="100" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="最大同时持仓数" prop="max_position_count">
              <el-input-number v-model="form.max_position_count" :min="1" :max="10" style="width:100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="单笔最大回撤 (%)" prop="max_single_drawdown">
              <el-input-number v-model="form.max_single_drawdown" :min="0.5" :max="20" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="日最大亏损 (%)" prop="daily_max_loss">
              <el-input-number v-model="form.daily_max_loss" :min="1" :max="30" :step="0.5" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="连续亏损暂停 (单)">
              <el-row :gutter="8">
                <el-col :span="12">
                  <el-input-number v-model="form.consecutive_loss_pause" :min="1" :max="20" style="width:100%;" />
                </el-col>
                <el-col :span="12">
                  <el-input-number v-model="form.cooldown_hours" :min="1" :max="168" style="width:100%;" />
                  <div class="text-dim" style="font-size:12px;">冷却时长 (小时)</div>
                </el-col>
              </el-row>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">保存</el-button>
      </template>
    </el-dialog>

    <!-- EMV 信号诊断对话框 -->
    <el-dialog
      v-model="diagVisible"
      title="策略评分诊断 — 7因子信号引擎"
      width="720px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="diagLoading" style="min-height:300px;">
        <template v-if="diagData">
          <!-- 评分概要 -->
          <div class="diag-summary">
            <div class="diag-item">
              <span class="diag-label">品种/周期</span>
              <span class="diag-value">{{ diagData.symbol }} / {{ diagData.timeframe }}</span>
            </div>
            <div class="diag-item">
              <span class="diag-label">收盘价</span>
              <span class="diag-value monospace">${{ Number(diagData.candle_close_price).toFixed(2) }}</span>
            </div>
            <div class="diag-item">
              <span class="diag-label">综合评分</span>
              <span class="diag-value" :class="diagData.total_score >= 5 ? 'text-profit' : 'text-loss'">
                {{ diagData.total_score }} / 10
              </span>
            </div>
            <div class="diag-item">
              <span class="diag-label">方向</span>
              <el-tag :type="diagData.direction===1?'success':diagData.direction===2?'danger':'info'" effect="dark" size="small">
                {{ diagData.direction_name }}
              </el-tag>
            </div>
            <div class="diag-item">
              <span class="diag-label">触发</span>
              <el-tag :type="diagData.trigger_trade ? 'success' : 'info'" effect="dark" size="small">
                {{ diagData.trigger_trade ? '是 → 可执行做多' : '否 → 观望' }}
              </el-tag>
            </div>
          </div>

          <!-- 10层过滤漏斗 -->
          <div class="filter-funnel">
            <div class="funnel-title">EMV 10层信号过滤</div>
            <div
              v-for="(layer, idx) in emvLayers"
              :key="layer.key"
              class="funnel-row"
              :class="layer.passed ? 'pass' : 'fail'"
            >
              <div class="funnel-step">{{ idx + 1 }}</div>
              <div class="funnel-content">
                <div class="funnel-name">{{ layer.name }}</div>
                <div class="funnel-desc">{{ layer.desc }}</div>
              </div>
              <div class="funnel-status">
                <el-tag :type="layer.passed ? 'success' : 'danger'" effect="dark" size="small">
                  {{ layer.passed ? '✓ 通过' : '✗ 拦截' }}
                </el-tag>
              </div>
            </div>
          </div>

          <!-- EMV指标快照 -->
          <div class="diag-section" v-if="diagData.indicators">
            <div class="section-title">EMV 指标快照</div>
            <div class="indicator-grid">
              <div class="ind-item">
                <span class="ind-label">EMV</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.emv) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">EMV信号线</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.emv_signal) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">EMV上穿</span>
                <el-tag :type="diagData.indicators.emv_cross_up ? 'success' : 'info'" size="small" effect="dark">
                  {{ diagData.indicators.emv_cross_up ? '是' : '否' }}
                </el-tag>
              </div>
              <div class="ind-item">
                <span class="ind-label">MA7</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.ma7) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">MA25</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.ma25) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">MA99</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.ma99) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">RSI14</span>
                <span class="ind-value monospace" :class="rsiClass(diagData.indicators.rsi14)">{{ formatNum(diagData.indicators.rsi14) }}</span>
              </div>
              <div class="ind-item">
                <span class="ind-label">ATR14</span>
                <span class="ind-value monospace">{{ formatNum(diagData.indicators.atr14) }}</span>
              </div>
            </div>
          </div>

          <!-- 7因子快照 -->
          <div class="diag-section" v-if="diagData.factor_scores">
            <div class="section-title">
              7因子信号引擎
              <el-tag size="small" effect="plain" style="margin-left:8px;">{{ regimeCN(diagData.market_regime) }}</el-tag>
            </div>
            <div class="factor-grid">
              <div v-for="(score, key) in diagData.factor_scores" :key="key" class="factor-cell">
                <div class="fc-name">{{ factorCN(key) }}</div>
                <div class="fc-score" :class="score >= 0 ? 'text-profit' : 'text-loss'">
                  {{ score >= 0 ? '+' : '' }}{{ score.toFixed(1) }}
                </div>
                <div class="fc-conf text-dim">
                  {{ (diagData.factor_confidence?.[key] || 0).toFixed(0) }}%
                </div>
                <div class="fc-bar">
                  <div class="fc-bar-fill" :class="score >= 0 ? 'pos' : 'neg'"
                    :style="{ width: Math.min(100, Math.abs(score) * 10) + '%' }">
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 评分理由 -->
          <div class="diag-section" v-if="diagData.emv_reasons && diagData.emv_reasons.length">
            <div class="section-title">过滤理由</div>
            <div v-for="r in diagData.emv_reasons" :key="r" class="reason-item">• {{ r }}</div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="primary" @click="runDiag" :loading="diagLoading" :disabled="!diagRow">重新诊断</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Plus, Search, RefreshRight, Edit, Histogram, Delete, MagicStick, Promotion, View } from '@element-plus/icons-vue'
import { SYMBOL_META } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const router = useRouter()
const f = reactive({ is_active: undefined, run_mode: undefined, keyword: '' })
const rows = ref([])
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/strategies`, { ...f, page_size: 100 })
    rows.value = r.items || []
  } catch (e) {
    console.warn('[Strategy] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

// ------------ 表单 ------------
const formVisible = ref(false)
const formRef = ref(null)
const submitting = ref(false)
const tplLoading = ref(false)
const emptyForm = () => ({
  id: null, strategy_name: '', description: '', symbols: [],
  exchange_id: null, timeframe: '1h,4h', direction_mode: 0, run_mode: 3,
  score_threshold: 5.0, strong_score_threshold: 8.0,
  weight_technical: 0.4, weight_news: 0.3, weight_ai: 0.3,
  leverage_mode: 2, leverage_fixed: 3,
  leverage_low_score: 3, leverage_mid_score: 5, leverage_high_score: 8,
  tp_ratio: 4.0, sl_ratio: 2.0, use_exchange_tpsl: true,
  single_position_ratio: 10.0, total_position_ratio: 50.0, max_position_count: 3,
  max_single_drawdown: 2.0, daily_max_loss: 5.0,
  consecutive_loss_pause: 3, cooldown_hours: 24, priority: 0,
})
const form = reactive(emptyForm())

const rules = {
  strategy_name: [{ required: true, message: '请输入策略名称', trigger: 'blur' }],
  symbols: [{ required: true, type: 'array', min: 1, message: '至少选择一个交易品种', trigger: 'change' }],
  run_mode: [{ required: true, message: '请选择运行模式', trigger: 'change' }],
  timeframe: [{ required: true, message: '请选择K线周期', trigger: 'change' }],
}

const openForm = (row) => {
  Object.assign(form, emptyForm())
  if (row) {
    Object.assign(form, JSON.parse(JSON.stringify(row)))
    form.symbols = Array.isArray(row.symbols) ? [...row.symbols] : []
  }
  formVisible.value = true
}

const applyTemplate = async () => {
  tplLoading.value = true
  try {
    const tpl = await http.get(`${API_PREFIX}/strategies/default-template`)
    Object.assign(form, emptyForm(), tpl || {})
    form.id = null
    formVisible.value = true
    ElMessage.success('已填充推荐模板，请检查后保存')
  } catch (e) {
    ElMessage.error('模板加载失败')
  } finally {
    tplLoading.value = false
  }
}

const submitForm = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (ok) => {
    if (!ok) return
    const sum = form.weight_technical + form.weight_news + form.weight_ai
    if (Math.abs(sum - 1) > 0.01) {
      ElMessage.warning(`三项权重之和必须等于 1.0，当前 ${sum.toFixed(2)}`)
      return
    }
    if (form.symbols.length === 0) {
      ElMessage.warning('请至少选择一个交易品种')
      return
    }
    submitting.value = true
    try {
      const payload = { ...form }
      delete payload.id
      if (form.id) {
        await http.put(`${API_PREFIX}/strategies/${form.id}`, payload)
        ElMessage.success('策略已更新')
      } else {
        await http.post(`${API_PREFIX}/strategies`, payload)
        ElMessage.success('策略创建成功')
      }
      formVisible.value = false
      load()
    } catch (e) {
      // 错误由 request 拦截器处理
    } finally {
      submitting.value = false
    }
  })
}

const toggle = async (row) => {
  try {
    await http.post(`${API_PREFIX}/strategies/${row.id}/toggle?active=${row.is_active}`)
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch { row.is_active = !row.is_active; ElMessage.error('策略启停失败，请稍后重试') }
}
const runNow = async (row) => {
  try {
    await ElMessageBox.confirm(
      `立即执行策略「${row.strategy_name}」？将跑一遍评分并根据运行模式决定是否下单。`,
      '立即执行',
      { type: 'warning' }
    )
    const r = await http.post(`${API_PREFIX}/strategies/${row.id}/run?execute_trade=${row.run_mode !== 3}`)
    ElMessage.success(r.message || '执行完成')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '执行失败')
  }
}
const backtest = (row) => router.push({ path: '/backtest', query: { strategy_id: row.id } })
const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`删除策略 ${row.strategy_name}？（有持仓时禁止删除）`, '确认', { type: 'warning' })
    await http.delete(`${API_PREFIX}/strategies/${row.id}`)
    ElMessage.success('删除成功')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败（可能仍有持仓）')
  }
}

// ------------ EMV 信号诊断 ------------
const diagVisible = ref(false)
const diagLoading = ref(false)
const diagData = ref(null)
const diagRow = ref(null)

// 10层过滤定义
const EMV_LAYERS = [
  { key: '1_emv_cross',   name: 'EMV上穿Signal',     desc: 'EMV主线穿越信号线 + 2根K线确认' },
  { key: '2_ma99_up',     name: 'MA99上升',           desc: '近10根MA99持续上升 → 大趋势多头' },
  { key: '3_bull_alignment', name: '多头排列',        desc: 'Close > MA25 > MA99，均线多头排列' },
  { key: '4_emv_strength',name: 'EMV强度',            desc: '|EMV| ≥ 0.7σ（30根标准差）' },
  { key: '5_rsi_range',   name: 'RSI中段',            desc: 'RSI ∈ [38, 68]，非超买超卖' },
  { key: '6_atr_vol',     name: 'ATR波动率',          desc: 'ATR14/ATR120 ≤ 1.5x，波动率不过热' },
  { key: '7_breakout',    name: '突破分位',           desc: 'Close ≥ 过去20根的65分位' },
  { key: '8_ma99_slope',  name: 'MA99斜率加速',       desc: 'MA99近30根涨幅 ≥ 0.7%' },
  { key: '9_price_above_ma99', name: '价格远离MA99',  desc: 'Close > MA99 × 1.025 (Gap ≥ 2.5%)' },
  { key: '10_win_rate_observe', name: '胜率观察期',   desc: '滚动24笔胜率 ≥ 15%（不足8笔不生效）' },
]

const emvLayers = ref([])
const formatNum = (v) => v != null ? Number(v).toFixed(2) : 'N/A'
const rsiClass = (v) => v > 70 ? 'text-loss' : v < 30 ? 'text-profit' : ''

// 7因子辅助
function factorCN(key) {
  const map = {
    market_regime: '市场状态', capital_flow: '资金流向',
    leverage: '杠杆集中度', liquidation: '清算压力',
    volatility: '波动率', news_sentiment: '新闻情绪',
    strategy_advantage: '策略优势',
  }
  return map[key] || key
}
function regimeCN(r) {
  const map = {
    ranging: '震荡市', strong_trend_up: '强势上涨', strong_trend_down: '强势下跌',
    weak_trend_up: '弱势上涨', weak_trend_down: '弱势下跌',
    breakout_up: '向上突破', breakout_down: '向下突破',
  }
  return map[r] || r || '未知'
}

const openDiag = (row) => {
  diagRow.value = row
  diagData.value = null
  diagVisible.value = true
  runDiag()
}

const runDiag = async () => {
  if (!diagRow.value) return
  diagLoading.value = true
  diagData.value = null
  try {
    const symbol = (diagRow.value.symbols && diagRow.value.symbols[0]) || 'XAU'
    const tf = diagRow.value.timeframe === '4h' ? '4h' : '4h'
    const r = await http.post(`${API_PREFIX}/strategies/${diagRow.value.id}/score-symbol`, {
      symbol, timeframe: tf, execute_trade: false
    })
    diagData.value = r
    // 构建过滤层状态
    const fd = r.emv_filter_details || {}
    emvLayers.value = EMV_LAYERS.map(l => ({
      ...l,
      passed: !!fd[l.key]
    }))
  } catch (e) {
    ElMessage.error(e?.message || '评分失败，请确保已绑定交易所并同步K线数据')
  } finally {
    diagLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* EMV 信号诊断样式 */
.diag-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  padding: 12px 16px;
  background: #131e2e;
  border-radius: 8px;
  margin-bottom: 16px;
}
.diag-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.diag-label {
  font-size: 12px;
  color: #6b7a8d;
}
.diag-value {
  font-size: 15px;
  font-weight: 600;
}

.filter-funnel {
  margin-bottom: 20px;
}
.funnel-title {
  font-size: 14px;
  font-weight: 600;
  color: #c0ccda;
  margin-bottom: 8px;
  padding-left: 4px;
}
.funnel-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 3px;
  border-radius: 6px;
  border-left: 3px solid;
  transition: all 0.2s;
}
.funnel-row.pass {
  background: rgba(82, 196, 26, 0.06);
  border-left-color: #52c41a;
}
.funnel-row.fail {
  background: rgba(245, 34, 45, 0.06);
  border-left-color: #f5222d;
}
.funnel-step {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  background: #1e2a3a;
  color: #8c98a8;
  flex-shrink: 0;
}
.funnel-row.pass .funnel-step {
  background: rgba(82, 196, 26, 0.15);
  color: #52c41a;
}
.funnel-row.fail .funnel-step {
  background: rgba(245, 34, 45, 0.15);
  color: #f5222d;
}
.funnel-content {
  flex: 1;
  min-width: 0;
}
.funnel-name {
  font-size: 13px;
  font-weight: 600;
  color: #c0ccda;
}
.funnel-desc {
  font-size: 12px;
  color: #6b7a8d;
  margin-top: 2px;
}
.funnel-status {
  flex-shrink: 0;
}

.diag-section {
  margin-top: 16px;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #c0ccda;
  margin-bottom: 8px;
  padding-left: 4px;
}
.indicator-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.ind-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  background: #131e2e;
  border-radius: 6px;
}
.ind-label {
  font-size: 11px;
  color: #6b7a8d;
  margin-bottom: 4px;
}
.ind-value {
  font-size: 14px;
  font-weight: 600;
}
.reason-item {
  font-size: 12px;
  color: #8c98a8;
  padding: 4px 12px;
  line-height: 1.6;
}

/* 7因子网格 */
.factor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  padding: 8px 12px;
}
.factor-cell {
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  text-align: center;
}
.fc-name {
  font-size: 11px;
  color: #8c98a8;
  margin-bottom: 4px;
}
.fc-score {
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  margin-bottom: 2px;
}
.fc-conf {
  font-size: 10px;
  margin-bottom: 4px;
}
.fc-bar {
  height: 4px;
  background: var(--el-fill-color);
  border-radius: 2px;
  overflow: hidden;
}
.fc-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}
.fc-bar-fill.pos { background: #4ADE80; }
.fc-bar-fill.neg { background: #F87171; }
</style>
