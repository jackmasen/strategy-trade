<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><PieChart /></el-icon>当前持仓</h2>
        <div class="page-subtitle">实时持仓监控、一键平仓、止盈止损调整</div>
      </div>
      <div class="flex gap-12">
        <el-tag effect="dark" type="success">
          持仓中: <b style="margin-left:6px;">{{ rows.filter(r=>r.status===1).length }}</b>
        </el-tag>
        <el-tag effect="dark" type="info">
          总浮动盈亏:
          <b :class="totalUnrealized>=0?'text-profit':'text-loss'" style="margin-left:6px;">
            {{ totalUnrealized>=0?'+':'' }}${{ fmtMoney(totalUnrealized) }}
          </b>
        </el-tag>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="f.symbol" placeholder="品种" clearable style="width:140px;">
        <el-option v-for="(m, k) in SYMBOL_META" :key="k" :label="k" :value="k" />
      </el-select>
      <el-select v-model="f.side" placeholder="方向" clearable style="width:140px;">
        <el-option :value="1" label="做多" />
        <el-option :value="2" label="做空" />
      </el-select>
    </div>

    <div class="panel-card">
      <el-table :data="rows" v-loading="loading" :header-cell-style="{ background:'#192738' }">
        <el-table-column label="品种" width="130">
          <template #default="{ row }">
            <div class="flex gap-8">
              <span style="font-size:22px;">{{ SYMBOL_META[row.symbol]?.icon }}</span>
              <div>
                <div class="text-strong monospace">{{ row.symbol }}</div>
                <div class="text-dim" style="font-size:11px;">{{ SYMBOL_META[row.symbol]?.name }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="方向/杠杆" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.side===1?'success':'danger'" effect="dark">
              {{ row.side===1?'多':'空' }} {{ row.leverage }}x
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开仓价" width="130" align="right">
          <template #default="{ row }"><span class="monospace">${{ fmtMoney(row.entry_price) }}</span></template>
        </el-table-column>
        <el-table-column label="标记价" width="130" align="right">
          <template #default="{ row }"><span class="monospace text-info">${{ fmtMoney(row.mark_price) }}</span></template>
        </el-table-column>
        <el-table-column label="止盈价" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.tp_price" class="monospace text-profit">${{ fmtMoney(row.tp_price) }}</span>
            <span v-else class="text-dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="止损价" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.sl_price" class="monospace text-loss">${{ fmtMoney(row.sl_price) }}</span>
            <span v-else class="text-dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="仓位大小" width="150" align="right">
          <template #default="{ row }">
            <div class="monospace">${{ fmtMoney(row.quantity_usdt) }}</div>
            <div class="text-dim" style="font-size:11px;">保证金 ${{ fmtMoney(row.margin_used) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="浮动盈亏" width="170" align="right">
          <template #default="{ row }">
            <div class="monospace" :class="fmtPnlClass(row.unrealized_pnl)" style="font-size:15px; font-weight:700;">
              {{ Number(row.unrealized_pnl)>=0?'+':'' }}${{ fmtMoney(row.unrealized_pnl) }}
            </div>
            <div :class="fmtPnlClass(row.pnl_ratio)" style="font-size:11px;">
              {{ Number(row.pnl_ratio)>=0?'+':'' }}{{ Number(row.pnl_ratio).toFixed(2) }}%
            </div>
            <div class="mt-8" style="height:4px; background:#1A2B3C; border-radius:2px; overflow:hidden;">
              <div
                :style="{
                  width: Math.min(100, Math.abs(Number(row.pnl_ratio)) / 5 * 100) + '%',
                  background: Number(row.unrealized_pnl)>=0 ? '#4ADE80' : '#F87171',
                  height: '100%',
                }"
              ></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="持仓时长" width="120" align="center">
          <template #default="{ row }"><span class="monospace">{{ row.holding_minutes }}m</span></template>
        </el-table-column>
        <el-table-column label="最大回撤" width="110" align="center">
          <template #default="{ row }">
            <span class="text-loss">-{{ Number(row.max_drawdown_ratio).toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <el-button size="small" type="success" plain :icon="Top" @click="addTp(row)">TP</el-button>
            <el-button size="small" type="danger" plain :icon="Bottom" @click="addSl(row)">SL</el-button>
            <el-button size="small" type="warning" :icon="SwitchButton" @click="closeOne(row)">平仓</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- TP/SL 调整对话框 -->
    <el-dialog v-model="tpslVisible" :title="tpslMode==='tp'?'调整止盈价':'调整止损价'" width="400px">
      <el-form :model="tpslForm" :rules="tpslRules" ref="tpslRef" label-width="80px">
        <el-form-item label="品种">
          <span class="text-strong">{{ tpslTarget?.symbol }}</span>
          <el-tag :type="tpslTarget?.side===1?'success':'danger'" effect="dark" style="margin-left:8px;">
            {{ tpslTarget?.side===1?'多':'空' }} {{ tpslTarget?.leverage }}x
          </el-tag>
        </el-form-item>
        <el-form-item label="当前价格">
          <span class="monospace">${{ fmtMoney(tpslTarget?.mark_price) }}</span>
        </el-form-item>
        <el-form-item label="当前TP/SL">
          <span class="monospace">{{ tpslMode==='tp'?'止盈':'止损' }}: ${{ fmtMoney(tpslMode==='tp'?(tpslTarget?.tp_price||0):(tpslTarget?.sl_price||0)) }}</span>
        </el-form-item>
        <el-form-item label="新价格" prop="value">
          <el-input-number v-model="tpslForm.value" :precision="2" :step="0.01" :min="0" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tpslVisible=false">取消</el-button>
        <el-button type="primary" @click="submitTpsl">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { PieChart, Top, Bottom, SwitchButton } from '@element-plus/icons-vue'
import { SYMBOL_META, fmtMoney, fmtPnlClass } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const f = reactive({ symbol: undefined, side: undefined })
const rows = ref([])
const loading = ref(true)
const totalUnrealized = computed(() => rows.value.reduce((s, r) => s + Number(r.unrealized_pnl || 0), 0))

const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/trades/positions`, { ...f })
    // 兼容后端不同字段命名（tp / tp_price, unrealized_pnl_pct / pnl_ratio, open_time / entry_time 等）
    rows.value = (r.items || []).map(p => ({
      ...p,
      id: p.id,
      symbol: p.symbol,
      side: p.side,
      leverage: p.leverage || 3,
      entry_price: Number(p.entry_price || 0),
      mark_price:  Number(p.mark_price  || 0),
      tp_price: Number(p.tp || p.tp_price || 0),
      sl_price: Number(p.sl || p.sl_price || 0),
      quantity_usdt: Number(p.quantity_usdt || p.nominal || 0),
      margin_used: Number(p.margin || p.margin_used || 0),
      unrealized_pnl: Number(p.unrealized_pnl || 0),
      pnl_ratio: Number(p.unrealized_pnl_pct ?? p.pnl_ratio ?? 0),
      max_drawdown_ratio: Number(p.max_drawdown_ratio || 0),
      holding_minutes: p.holding_minutes != null ? p.holding_minutes :
        (p.open_time ? Math.round((Date.now() - new Date(p.open_time).getTime())/60000) : 0),
    }))
  } catch (e) {
    console.warn('[Positions] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

// ---- 调整 TP/SL 对话框 ----
const tpslVisible = ref(false)
const tpslMode = ref('tp') // 'tp' or 'sl'
const tpslTarget = ref(null)
const tpslValue = ref(null)
const tpslRef = ref(null)
const tpslRules = {
  value: [
    { required: true, message: '请输入价格', trigger: 'blur' },
    { type: 'number', min: 0, message: '价格必须大于0', trigger: 'blur' },
  ],
}
const tpslForm = reactive({ value: null })

const openTpsl = (row, mode) => {
  tpslMode.value = mode
  tpslTarget.value = row
  tpslForm.value = Number(mode === 'tp' ? (row.tp_price || 0) : (row.sl_price || 0))
  tpslVisible.value = true
}
const submitTpsl = async () => {
  if (!tpslRef.value) return
  await tpslRef.value.validate(async (ok) => {
    if (!ok) return
    try {
      const params = {}
      if (tpslMode.value === 'tp') params.tp_price = tpslForm.value
      else params.sl_price = tpslForm.value
      await http.put(`${API_PREFIX}/trades/positions/${tpslTarget.value.id}/tpsl`, null, { params })
      ElMessage.success(`${tpslTarget.value.symbol} ${tpslMode.value==='tp'?'止盈':'止损'}价已更新为 $${tpslForm.value}`)
      tpslVisible.value = false
      load()
    } catch (e) {
      ElMessage.error(e?.message || '更新失败')
    }
  })
}
const addTp = (row) => openTpsl(row, 'tp')
const addSl = (row) => openTpsl(row, 'sl')

const closeOne = async (row) => {
  const upnl = Number(row.unrealized_pnl || 0)
  try {
    await ElMessageBox.confirm(
      `确定平仓 ${row.symbol}？方向${row.side===1?'多':'空'} ${row.leverage}x\n当前浮盈 ${upnl>=0?'+':''}${upnl.toFixed(2)} USDT`,
      '平仓确认',
      { type: 'warning', confirmButtonText: '立即平仓', cancelButtonText: '取消' }
    )
    await http.post(`${API_PREFIX}/trades/positions/${row.id}/close`)
    ElMessage.success('平仓指令已提交')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '平仓失败')
  }
}
onMounted(load)
</script>
