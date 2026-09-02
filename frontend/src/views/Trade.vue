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
              {{ row.side === 1 ? '多' : '空' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="['success','info','danger'][row.order_type-1]">
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
            <el-tag size="small" effect="dark" :type="ORDER_STATUS_META[row.status]?.type">
              {{ ORDER_STATUS_META[row.status]?.name }}
            </el-tag>
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
    width="640px"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <el-form :model="orderForm" :rules="rules" ref="formRef" label-width="130px">
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="交易所子账号" prop="exchange_account_id">
            <el-select v-model="orderForm.exchange_account_id" placeholder="选择子账号" style="width:100%;" filterable>
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
            <el-select v-model="orderForm.symbol" style="width:100%;">
              <el-option v-for="(m,k) in SYMBOL_META" :key="k" :label="`${m.icon} ${k} ${m.name}`" :value="k" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="8">
          <el-form-item label="方向" prop="side">
            <el-radio-group v-model="orderForm.side">
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
            <el-input-number v-model="orderForm.quantity_usdt" :min="10" :max="100000" :step="50" style="width:100%;" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="占用保证金">
            <span class="monospace text-info" style="font-size:16px;">≈ ${{ estimateMargin }}</span>
            <span class="text-dim" style="margin-left:8px;">（本金 × 杠杆倒数）</span>
          </el-form-item>
        </el-col>
      </el-row>

      <el-divider>止盈止损（优先用绝对价格，没填则按%自动计算）</el-divider>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="止盈比例 (%)">
            <el-input-number v-model="orderForm.tp_ratio_pct" :min="0.5" :max="50" :step="0.5" style="width:100%;" />
            <div class="text-dim" style="font-size:12px;">预期盈利 ≈ <span class="text-profit">+${{ estimateTpPnl }}</span></div>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="止损比例 (%)">
            <el-input-number v-model="orderForm.sl_ratio_pct" :min="0.3" :max="30" :step="0.5" style="width:100%;" />
            <div class="text-dim" style="font-size:12px;">最大亏损 ≈ <span class="text-loss">${{ estimateSlPnl }}</span></div>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="止盈价 (绝对)">
            <el-input-number v-model="orderForm.tp_price" :precision="4" :controls="false" placeholder="留空则按比例计算" style="width:100%;" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="止损价 (绝对)">
            <el-input-number v-model="orderForm.sl_price" :precision="4" :controls="false" placeholder="留空则按比例计算" style="width:100%;" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-alert
        title="风险提示" type="warning" :closable="false" show-icon
        description="合约交易具有极高风险，下单前请确保交易所API已开通期货交易权限、已划转保证金到合约账户；所有盈亏由账户实际成交为准。"
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
const estimateMargin = computed(() => {
  const q = Number(orderForm.quantity_usdt || 0)
  const lv = Number(orderForm.leverage || 1)
  return (q / lv).toFixed(2)
})
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
      ElMessage.success(`下单成功：订单号 #${r.order_id}，方向${payload.side===1?'多':'空'} ${orderForm.symbol} ${payload.quantity_usdt}U`)
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
