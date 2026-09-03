<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><TrendCharts /></el-icon>交易订单</h2>
        <div class="page-subtitle">查看所有下单记录，支持手动下单、撤单</div>
      </div>
      <el-button type="warning" :icon="Plus" size="large" @click="manualOrder">手动下单</el-button>
    </div>

    <div class="filter-bar">
      <el-select v-model="f.status" placeholder="状态" clearable style="width:160px;">
        <el-option v-for="(m, k) in ORDER_STATUS_META" :key="k" :label="m.name" :value="Number(k)" />
      </el-select>
      <el-select v-model="f.side" placeholder="方向" clearable style="width:140px;">
        <el-option :value="1" label="做多" />
        <el-option :value="2" label="做空" />
      </el-select>
      <el-select v-model="f.symbol" placeholder="品种" clearable filterable style="width:140px;">
        <el-option v-for="(m, k) in SYMBOL_META" :key="k" :label="`${m.icon} ${k} ${m.name}`" :value="k" />
      </el-select>
      <el-date-picker v-model="f.range" type="datetimerange" start-placeholder="开始" end-placeholder="结束" style="width:360px;" />
      <el-button :icon="RefreshRight" @click="load">刷新</el-button>
    </div>

    <div class="panel-card">
      <el-table :data="rows" stripe v-loading="loading" :header-cell-style="{ background:'#192738' }">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ row.created_at }}</template>
        </el-table-column>
        <el-table-column prop="symbol" label="品种" width="90" align="center">
          <template #default="{ row }"><span class="monospace text-strong">{{ row.symbol }}</span></template>
        </el-table-column>
        <el-table-column label="方向" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="dark" :type="row.side===1?'success':'danger'">
              <span class="status-light" :class="row.side===1?'ok':'error'" style="margin-right:2px;"></span>
              {{ row.side === 1 ? '多' : '空' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="['success','info','danger'][row.order_type-1]">
              <span class="status-light" :class="row.order_type===1?'ok':(row.order_type===3?'error':'idle')" style="margin-right:2px;"></span>
              {{ ['开仓','平仓','强平'][row.order_type-1] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="杠杆" width="70" align="center">
          <template #default="{ row }"><span class="monospace text-warn">{{ row.leverage }}x</span></template>
        </el-table-column>
        <el-table-column label="下单价" width="120" align="right">
          <template #default="{ row }"><span class="monospace">{{ fmtMoney(row.order_price) }}</span></template>
        </el-table-column>
        <el-table-column label="成交均价" width="120" align="right">
          <template #default="{ row }"><span class="monospace">{{ fmtMoney(row.avg_fill_price) }}</span></template>
        </el-table-column>
        <el-table-column label="金额(USDT)" width="130" align="right">
          <template #default="{ row }"><span class="monospace">${{ fmtMoney(row.quantity_usdt) }}</span></template>
        </el-table-column>
        <el-table-column label="已实现盈亏" width="130" align="right">
          <template #default="{ row }">
            <span class="monospace" :class="fmtPnlClass(row.realized_pnl)">
              {{ Number(row.realized_pnl)>=0?'+':'' }}${{ fmtMoney(row.realized_pnl) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <span style="display:inline-flex;align-items:center;gap:4px;">
              <span class="status-light" :class="row.status===2?'ok':(row.status===3?'error':(row.status===1?'warn':'idle'))"></span>
              <el-tag size="small" effect="dark" :type="ORDER_STATUS_META[row.status]?.type">
                {{ ORDER_STATUS_META[row.status]?.name }}
              </el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="触发原因" width="120" align="center">
          <template #default="{ row }">
            {{ ['','手动','评分触发','止盈','止损','回撤超限','日亏损超限','冷静期','评分反转'][row.trigger_reason] || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right" align="center">
          <template #default="{ row }">
            <el-button v-if="row.status < 2" link type="primary" size="small" @click="cancel(row)">撤单</el-button>
            <span v-else class="text-dim">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>

  <!-- 手动下单对话框 -->
  <el-dialog
    v-model="dialogVisible"
    title="手动下单（市价开仓 + TP/SL）"
    width="700px"
    :close-on-click-modal="false"
    destroy-on-close
    @open="onDialogOpen"
  >
    <el-form :model="orderForm" :rules="rules" ref="formRef" label-width="130px">
      <!-- 实时价格显示区 -->
      <el-card shadow="never" class="price-panel" :class="{ 'price-long': orderForm.side === 1, 'price-short': orderForm.side === 2 }">
        <template #header>
          <div class="price-panel__header">
            <span class="price-panel__symbol">{{ orderForm.symbol || 'BTC' }}</span>
            <span class="price-panel__label">实时行情</span>
            <span v-if="tickerLoading" class="text-dim" style="font-size:12px;">加载中...</span>
            <span v-else-if="tickerData" class="price-panel__change" :class="tickerData.change_pct>=0?'text-profit':'text-loss'">
              {{ tickerData.change_pct>=0?'+':'' }}{{ tickerData.change_pct?.toFixed(2) || '0.00' }}%
            </span>
          </div>
        </template>
        <div class="price-panel__body">
          <div class="price-item">
            <span class="price-item__label">最新价</span>
            <span class="price-item__value">{{ tickerData?.last_price ? fmtMoney(tickerData.last_price, getPrecision(orderForm.symbol)) : '---' }}</span>
          </div>
          <div class="price-item">
            <span class="price-item__label">买一价 (Bid)</span>
            <span class="price-item__value price-bid">{{ tickerData?.bid_price ? fmtMoney(tickerData.bid_price, getPrecision(orderForm.symbol)) : '---' }}</span>
          </div>
          <div class="price-item">
            <span class="price-item__label">卖一价 (Ask)</span>
            <span class="price-item__value price-ask">{{ tickerData?.ask_price ? fmtMoney(tickerData.ask_price, getPrecision(orderForm.symbol)) : '---' }}</span>
          </div>
          <div class="price-item price-highlight">
            <span class="price-item__label">{{ orderForm.side === 1 ? '做多成交参考价' : '做空成交参考价' }}</span>
            <span class="price-item__value price-execution" :class="orderForm.side===1?'text-profit':'text-loss'">
              {{ executionPrice ? fmtMoney(executionPrice, getPrecision(orderForm.symbol)) : '---' }}
            </span>
            <span class="price-item__tag" :class="orderForm.side===1?'tag-long':'tag-short'">{{ orderForm.side===1?'以卖价买入':'以买价卖出' }}</span>
          </div>
        </div>
      </el-card>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="交易所子账号" prop="exchange_account_id">
            <el-select v-model="orderForm.exchange_account_id" placeholder="选择子账号" style="width:100%;" filterable @change="onAccountChange">
              <el-option
                v-for="a in accounts"
                :key="a.id"
                :label="`${EXCHANGE_META[a.exchange]?.name || ''} · ${a.sub_account_name || a.name || '#'+a.id} · 最大${a.leverage_max||10}x`"
                :value="a.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="交易品种" prop="symbol">
            <el-select v-model="orderForm.symbol" style="width:100%;" @change="onSymbolChange">
              <el-option v-for="(m,k) in SYMBOL_META" :key="k" :label="`${m.icon} ${k} ${m.name}`" :value="k" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="8">
          <el-form-item label="方向" prop="side">
            <el-radio-group v-model="orderForm.side" @change="onSideChange">
              <el-radio-button :value="1">
                <span style="color:#4ADE80;">买入 / 做多</span>
              </el-radio-button>
              <el-radio-button :value="2">
                <span style="color:#F87171;">卖出 / 做空</span>
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="杠杆倍数" prop="leverage">
            <el-input-number v-model="orderForm.leverage" :min="1" :max="currentMaxLeverage" :step="1" style="width:100%;" />
            <div class="text-dim" style="font-size:11px;margin-top:2px;">上限 {{ currentMaxLeverage }}x</div>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="保证金模式">
            <el-radio-group v-model="orderForm.margin_mode">
              <el-radio-button :value="1">全仓</el-radio-button>
              <el-radio-button :value="2">逐仓</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="下单金额(USDT)" prop="quantity_usdt">
            <el-input-number v-model="orderForm.quantity_usdt" :min="10" :max="100000" :step="50" style="width:100%;" @change="onAmountChange" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="占用保证金">
            <span class="monospace text-info" style="font-size:16px;">≈ ${{ estimateMargin }}</span>
            <span class="text-dim" style="margin-left:8px;">（本金 × 杠杆倒数）</span>
          </el-form-item>
        </el-col>
      </el-row>

      <el-divider>止盈止损</el-divider>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="止盈比例 (%)">
            <el-input-number v-model="orderForm.tp_ratio_pct" :min="0.5" :max="50" :step="0.5" style="width:100%;" @change="onTpSlChange" />
            <div class="text-dim" style="font-size:12px;">止盈价 ≈ <span class="text-profit">{{ estimateTpPrice }}</span></div>
            <div class="text-dim" style="font-size:11px;">预期盈利 ≈ <span class="text-profit">+${{ estimateTpPnl }}</span></div>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="止损比例 (%)">
            <el-input-number v-model="orderForm.sl_ratio_pct" :min="0.3" :max="30" :step="0.5" style="width:100%;" @change="onTpSlChange" />
            <div class="text-dim" style="font-size:12px;">止损价 ≈ <span class="text-loss">{{ estimateSlPrice }}</span></div>
            <div class="text-dim" style="font-size:11px;">最大亏损 ≈ <span class="text-loss">${{ estimateSlPnl }}</span></div>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="止盈价 (绝对)">
            <el-input-number v-model="orderForm.tp_price" :precision="getPrecision(orderForm.symbol)" :controls="false" placeholder="留空则按比例自动计算" style="width:100%;" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="止损价 (绝对)">
            <el-input-number v-model="orderForm.sl_price" :precision="getPrecision(orderForm.symbol)" :controls="false" placeholder="留空则按比例自动计算" style="width:100%;" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-alert
        title="风险提示" type="warning" :closable="false" show-icon
        description="合约交易具有极高风险，下单前请确保交易所API已开通期货交易权限、已划转保证金到合约账户；所有盈亏由账户实际成交为准。做多参考卖价(Ask)，做空参考买价(Bid)。"
        style="margin-top:8px;"
      />
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button
        type="primary"
        :type="orderForm.side === 1 ? 'success' : 'danger'"
        @click="submitOrder"
        :loading="submitting"
      >
        确认 {{ orderForm.side === 1 ? '做多' : '做空' }} {{ orderForm.symbol }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { TrendCharts, Plus, RefreshRight } from '@element-plus/icons-vue'
import { SYMBOL_META, ORDER_STATUS_META, EXCHANGE_META, fmtMoney, fmtPnlClass } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const f = reactive({ status: undefined, side: undefined, symbol: undefined, range: [] })
const rows = ref([])
const accounts = ref([])
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/trades/orders`, { ...f, page_size: 100, start: f.range?.[0], end: f.range?.[1] })
    rows.value = r.items || []
  } catch (e) {
    console.warn('[Trade] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

// 加载交易所子账号（下拉选择）
const loadAccounts = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/exchange/accounts`, { status: 1, page_size: 100 })
    accounts.value = r.items || []
  } catch {}
}

// ---------- 实时行情 ----------
const tickerData = ref(null)
const tickerLoading = ref(false)
const tickerTimer = ref(null)

function getPrecision(symbol) {
  const p = { BTC: 2, ETH: 2, SOL: 2, XAU: 2, XAG: 2, WTI: 2, TSLA: 2, NVDA: 2, AAPL: 2, MSFT: 2, TCEHY: 2 }
  return p[symbol] || 4
}

async function fetchTicker(symbol, silent = false) {
  if (!symbol) return
  tickerLoading.value = true
  try {
    const data = await http.get(`${API_PREFIX}/exchange/ticker/${symbol}`)
    // normalize change_pct_24h → change_pct for template compatibility
    if (data.change_pct_24h !== undefined && data.change_pct === undefined) {
      data.change_pct = data.change_pct_24h
    }
    tickerData.value = data
    if (!silent) ElMessage.success(`${symbol} 行情已更新`)
  } catch (e) {
    if (!silent) console.warn('[Trade] 行情获取失败:', e)
    tickerData.value = null
  } finally {
    tickerLoading.value = false
  }
}

function startTickerPoll(symbol) {
  stopTickerPoll()
  if (!symbol) return
  fetchTicker(symbol, true)
  tickerTimer.value = setInterval(() => fetchTicker(symbol, true), 5000)
}

function stopTickerPoll() {
  if (tickerTimer.value) {
    clearInterval(tickerTimer.value)
    tickerTimer.value = null
  }
}

// ---------- 手动下单对话框 ----------
const dialogVisible = ref(false)
const submitting = ref(false)
const emptyOrder = () => ({
  exchange_account_id: null, symbol: 'BTC', side: 1,
  quantity_usdt: 100, leverage: 5, margin_mode: 1,
  tp_price: null, sl_price: null,
  tp_ratio_pct: 4.0, sl_ratio_pct: 2.0,
  order_type: 1,
})
const orderForm = reactive(emptyOrder())
const formRef = ref(null)
const currentMaxLeverage = computed(() => {
  const acc = accounts.value.find(a => a.id === orderForm.exchange_account_id)
  return acc?.leverage_max || 10
})
const rules = {
  exchange_account_id: [{ required: true, message: '请选择交易所子账号', trigger: 'change' }],
  symbol: [{ required: true, message: '请选择交易品种', trigger: 'change' }],
  quantity_usdt: [
    { required: true, message: '请输入下单金额', trigger: 'blur' },
    { type: 'number', min: 10, message: '最小下单金额 10 USDT', trigger: 'blur' },
  ],
  leverage: [{ required: true, type: 'number', min: 1, message: '杠杆至少 1 倍', trigger: 'blur' }],
}

// 执行价格（做多=ask，做空=bid）
const executionPrice = computed(() => {
  if (!tickerData.value) return null
  if (orderForm.side === 1) {
    return tickerData.value.ask_price || tickerData.value.last_price
  } else {
    return tickerData.value.bid_price || tickerData.value.ask_price || tickerData.value.last_price
  }
})

// 保证金
const estimateMargin = computed(() => {
  const q = Number(orderForm.quantity_usdt || 0)
  const lv = Number(orderForm.leverage || 1)
  return (q / lv).toFixed(2)
})

// 止盈止损价格（基于执行价格）
const rawExecPrice = computed(() => executionPrice.value || 0)

function calcTpPrice() {
  const exec = rawExecPrice.value
  if (!exec) return null
  const tpAbs = orderForm.tp_price
  if (tpAbs && tpAbs > 0) return tpAbs
  if (orderForm.side === 1) {
    return exec * (1 + orderForm.tp_ratio_pct / 100)
  } else {
    return exec * (1 - orderForm.tp_ratio_pct / 100)
  }
}

function calcSlPrice() {
  const exec = rawExecPrice.value
  if (!exec) return null
  const slAbs = orderForm.sl_price
  if (slAbs && slAbs > 0) return slAbs
  if (orderForm.side === 1) {
    return exec * (1 - orderForm.sl_ratio_pct / 100)
  } else {
    return exec * (1 + orderForm.sl_ratio_pct / 100)
  }
}

const estimateTpPrice = computed(() => {
  const p = calcTpPrice()
  return p ? fmtMoney(p, getPrecision(orderForm.symbol)) : '---'
})

const estimateSlPrice = computed(() => {
  const p = calcSlPrice()
  return p ? fmtMoney(p, getPrecision(orderForm.symbol)) : '---'
})

// 预估盈亏（基于执行价格）
const estimateTpPnl = computed(() => {
  const q = Number(orderForm.quantity_usdt || 0)
  const tp = Number(orderForm.tp_ratio_pct || 0)
  return (q * tp / 100).toFixed(2)
})

const estimateSlPnl = computed(() => {
  const q = Number(orderForm.quantity_usdt || 0)
  const sl = Number(orderForm.sl_ratio_pct || 0)
  return (- q * sl / 100).toFixed(2)
})

// 选择子账号后，自动设置杠杆为子账号最大值
watch(() => orderForm.exchange_account_id, (id) => {
  const acc = accounts.value.find(a => a.id === id)
  if (acc) {
    orderForm.leverage = acc.leverage_max || 10
  }
})

// 品种变化 → 刷新行情
watch(() => orderForm.symbol, (newSym) => {
  startTickerPoll(newSym)
})

// 方向变化 → 重新计算TP/SL价格提示
watch(() => orderForm.side, () => {
  // 价格面板会自动更新
})

function onDialogOpen() {
  if (!tickerData.value && orderForm.symbol) {
    startTickerPoll(orderForm.symbol)
  }
}

function onSymbolChange() {
  startTickerPoll(orderForm.symbol)
  orderForm.tp_price = null
  orderForm.sl_price = null
}

function onSideChange() {
  orderForm.tp_price = null
  orderForm.sl_price = null
}

function onAccountChange() {
  const acc = accounts.value.find(a => a.id === orderForm.exchange_account_id)
  if (acc) orderForm.leverage = acc.leverage_max || 10
}

function onAmountChange() {
  // 金额变化不直接影响TP/SL
}

function onTpSlChange() {
  // TP/SL比例变化，价格提示自动更新
}

const manualOrder = () => {
  if (!accounts.value.length) loadAccounts()
  Object.assign(orderForm, emptyOrder())
  if (accounts.value.length) orderForm.exchange_account_id = accounts.value[0].id
  dialogVisible.value = true
}
const submitOrder = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (ok) => {
    if (!ok) return
    submitting.value = true
    try {
      const payload = { ...orderForm }
      if (!payload.tp_price) delete payload.tp_price
      if (!payload.sl_price) delete payload.sl_price
      const r = await http.post(`${API_PREFIX}/trades/orders/manual`, payload)
      ElMessage.success(`下单成功：订单号 #${r.order_id}，方向${payload.side===1?'多':'空'} ${orderForm.symbol}，参考价${fmtMoney(r.execution_price || r.entry_price, getPrecision(orderForm.symbol))}，止损${fmtMoney(r.sl, getPrecision(orderForm.symbol))}`)
      dialogVisible.value = false
      load()
    } finally {
      submitting.value = false
    }
  })
}

const cancel = async (row) => {
  try {
    await ElMessageBox.confirm('撤销订单？', '确认', { type: 'warning' })
    await http.post(`${API_PREFIX}/trades/orders/${row.id}/cancel`)
    ElMessage.success('已撤单')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '撤单失败')
  }
}
onMounted(() => { load(); loadAccounts() })
</script>

<style scoped>
.price-panel {
  margin-bottom: 16px;
  border: 1px solid #334155;
  border-radius: 8px;
  background: #0f172a;
}
.price-panel.price-long {
  border-color: #16a34a;
}
.price-panel.price-short {
  border-color: #dc2626;
}
.price-panel__header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.price-panel__symbol {
  font-size: 18px;
  font-weight: 700;
  color: #f1f5f9;
}
.price-panel__label {
  font-size: 13px;
  color: #94a3b8;
}
.price-panel__change {
  margin-left: auto;
  font-size: 14px;
  font-weight: 600;
}
.price-panel__body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 24px;
  padding: 4px 0;
}
.price-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
}
.price-item.price-highlight {
  grid-column: 1 / -1;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
}
.price-item__label {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
  min-width: 90px;
}
.price-item__value {
  font-size: 15px;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}
.price-bid { color: #60a5fa; }
.price-ask { color: #f472b6; }
.price-execution {
  font-size: 18px;
  font-weight: 700;
}
.price-item__tag {
  margin-left: auto;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}
.tag-long {
  background: rgba(74,222,128,0.15);
  color: #4ade80;
  border: 1px solid rgba(74,222,128,0.3);
}
.tag-short {
  background: rgba(248,113,113,0.15);
  color: #f87171;
  border: 1px solid rgba(248,113,113,0.3);
}
</style>
