<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Histogram /></el-icon>历史回测中心</h2>
        <div class="page-subtitle">基于历史K线+新闻数据模拟策略表现，验证评分体系有效性</div>
      </div>
      <el-button type="primary" size="large" :icon="Plus" @click="showCreate = true">新建回测</el-button>
    </div>

    <el-row :gutter="16" v-if="current">
      <el-col :span="24">
        <div class="panel-card mb-16">
          <div class="flex-between mb-16">
            <div class="flex gap-12" style="flex-wrap:wrap;">
              <div><el-tag effect="dark" :type="statusColor(current.status)" round>
                {{ ['待执行','执行中','成功','失败'][current.status] }}
              </el-tag></div>
              <div>
                <b style="color:#F0F4F8;">{{ current.run_name }}</b>
                <span class="text-dim" style="margin-left:10px;">
                  {{ current.date_start?.slice(0,10) }} ~ {{ current.date_end?.slice(0,10) }}
                </span>
              </div>
              <el-tag effect="plain" size="small">品种: {{ (current.symbols||[]).join('/') }}</el-tag>
              <el-tag effect="plain" size="small">周期: {{ current.timeframe }}</el-tag>
              <el-tag effect="plain" size="small">初始资金: ${{ fmtMoney(current.initial_capital) }}</el-tag>
            </div>
            <div v-if="current.status === 1" class="flex gap-8">
              <el-progress :percentage="current.progress" :stroke-width="10" style="width:260px;" status="success" />
            </div>
          </div>

          <el-row :gutter="12" v-if="current.status === 2">
            <el-col :span="3" v-for="m in metrics" :key="m.key">
              <div class="mini-metric">
                <div class="text-dim" style="font-size:12px;">{{ m.label }}</div>
                <div class="monospace" :class="m.cls" :style="{fontSize: m.big ? '22px' : '18px', fontWeight: 700}">
                  {{ m.value }}<span class="unit" v-if="m.unit">{{ m.unit }}</span>
                </div>
              </div>
            </el-col>
          </el-row>

          <div v-if="current.status === 2" class="mt-16" style="height: 300px;">
            <v-chart :option="equityChart" autoresize style="height: 100%;" />
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 列表 -->
    <div class="panel-card">
      <div class="panel-card__header">
        <span class="panel-card__title">回测任务列表</span>
        <div class="text-dim" style="font-size:12px;">共 {{ list.length }} 条记录</div>
      </div>
      <div class="panel-card__body" style="padding:0;">
        <el-table :data="list" v-loading="loading" :header-cell-style="{ background:'#192738' }">
          <el-table-column label="任务" min-width="220">
            <template #default="{ row }">
              <span class="text-strong">{{ row.run_name }}</span>
              <div class="text-dim" style="font-size:11px; margin-top:4px;">
                {{ row.date_start?.slice(0,10) }} ~ {{ row.date_end?.slice(0,10) }} · {{ row.timeframe }} · {{ row.symbols?.join('/') }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="statusColor(row.status)" effect="dark" round size="small">
                {{ ['待执行','执行中','成功','失败'][row.status] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="总收益率" width="110" align="right">
            <template #default="{ row }">
              <span class="monospace" :class="fmtPnlClass(row.total_return_pct)" style="font-weight:600;">
                {{ Number(row.total_return_pct||0)>=0?'+':'' }}{{ Number(row.total_return_pct||0).toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="最大回撤" width="100" align="right">
            <template #default="{ row }"><span class="text-loss monospace">-{{ Number(row.max_drawdown_pct||0).toFixed(2) }}%</span></template>
          </el-table-column>
          <el-table-column label="夏普" width="80" align="center">
            <template #default="{ row }">
              <span :class="Number(row.sharpe_ratio)>=1.5?'text-profit':'text-warn'" class="monospace">
                {{ Number(row.sharpe_ratio||0).toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="胜率" width="90" align="center">
            <template #default="{ row }"><span class="monospace">{{ Number(row.win_rate||0).toFixed(1) }}%</span></template>
          </el-table-column>
          <el-table-column label="盈亏比" width="90" align="center">
            <template #default="{ row }"><span class="monospace">{{ Number(row.profit_factor||0).toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column label="总交易数" width="100" align="center">
            <template #default="{ row }"><span class="monospace">{{ row.total_trades }}</span></template>
          </el-table-column>
          <el-table-column label="最大连胜/连败" width="130" align="center">
            <template #default="{ row }">
              <span class="text-profit">{{ row.max_consecutive_wins }}</span>
              <span class="text-dim"> / </span>
              <span class="text-loss">{{ row.max_consecutive_losses }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" :icon="View" @click="view(row)">查看</el-button>
              <el-button link type="primary" size="small" :icon="CopyDocument" @click="clone(row)">克隆</el-button>
              <el-button link type="danger" size="small" :icon="Delete" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 创建对话框 -->
    <el-dialog v-model="showCreate" title="新建回测任务" width="640px" top="6vh">
      <el-form label-width="110px">
        <el-form-item label="回测名称"><el-input v-model="form.run_name" placeholder="如 BTC-4H-评分阈值5" /></el-form-item>
        <el-form-item label="交易品种">
          <el-select v-model="form.symbols" multiple style="width:100%;">
            <el-option v-for="(m,k) in SYMBOL_META" :key="k" :label="`${m.icon} ${k} ${m.name}`" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间周期">
          <el-radio-group v-model="form.timeframe">
            <el-radio-button value="1h">1小时</el-radio-button>
            <el-radio-button value="4h">4小时</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="回测区间">
          <el-date-picker v-model="form.range" type="daterange" style="width:100%;" start-placeholder="开始日期" end-placeholder="结束日期" />
        </el-form-item>
        <el-form-item label="初始资金">
          <el-input-number v-model="form.initial_capital" :min="100" :step="1000" style="width:100%;" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="手续费率(%)"><el-input-number v-model="form.fee_rate" :step="0.01" :precision="3" style="width:100%;" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="滑点(%)"><el-input-number v-model="form.slippage" :step="0.01" :precision="3" style="width:100%;" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="关联策略">
          <el-select v-model="form.strategy_id" placeholder="不使用现存策略则使用下方自定义参数" clearable style="width:100%;">
            <el-option label="示例策略A" :value="1" />
            <el-option label="示例策略B" :value="2" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="submit">开始回测</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
// 统一使用全量 echarts：避免 vue-echarts + echarts/core 按需注册触发
// "registers.registerChartView is not a function"（同 Dashboard 根因）
import * as echarts from 'echarts'
import VChart from 'vue-echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Histogram, Plus, View, CopyDocument, Delete } from '@element-plus/icons-vue'
import { SYMBOL_META, fmtMoney, fmtPnlClass } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const showCreate = ref(false)
const current = ref(null)
const list = ref([])

const form = reactive({
  run_name: '', symbols: ['BTC','ETH'], timeframe: '4h',
  range: [], initial_capital: 10000, fee_rate: 0.04, slippage: 0.05, strategy_id: undefined,
})

const metrics = computed(() => {
  const c = current.value
  if (!c) return []
  return [
    { key:'ret',    label:'总收益率',  value: Number(c.total_return_pct||0).toFixed(2), unit:'%', cls: fmtPnlClass(c.total_return_pct), big: true },
    { key:'annual', label:'年化收益',  value: Number(c.annual_return_pct||0).toFixed(2), unit:'%', cls: fmtPnlClass(c.annual_return_pct) },
    { key:'mdd',    label:'最大回撤',  value: '-'+Number(c.max_drawdown_pct||0).toFixed(2), unit:'%', cls:'text-loss', big: true },
    { key:'sharpe', label:'夏普比率',  value: Number(c.sharpe_ratio||0).toFixed(2), cls: Number(c.sharpe_ratio)>=1.5?'text-profit':'text-warn' },
    { key:'sortino',label:'索提诺',    value: Number(c.sortino_ratio||0).toFixed(2), cls: 'text-info' },
    { key:'calmar', label:'卡玛比率',  value: Number(c.calmar_ratio||0).toFixed(2), cls: Number(c.calmar_ratio)>=1?'text-profit':'text-warn' },
    { key:'wr',     label:'胜率',      value: Number(c.win_rate||0).toFixed(1), unit:'%', cls: 'text-strong' },
    { key:'pf',     label:'盈亏比',    value: Number(c.profit_factor||0).toFixed(2), cls: Number(c.profit_factor)>=2?'text-profit':'text-warn' },
  ]
})

const equityChart = computed(() => {
  const curve = current.value?.equity_curve || []
  const dates = curve.map(x => x.date)
  const equity = curve.map(x => x.equity)
  const btc = curve.map(x => x.bench_btc)
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 50, top: 30, bottom: 30 },
    tooltip: { trigger:'axis', backgroundColor:'#1A2B3C', borderColor:'#29405A', textStyle:{color:'#D8E2EC'} },
    legend: { data:['策略权益','BTC买入持有'], textStyle:{ color:'#97A6B6' }, top: 4, right: 8 },
    xAxis: { type:'category', data: dates, axisLine:{lineStyle:{color:'#243447'}}, axisLabel:{color:'#6B7C90', fontSize:10} },
    yAxis: { type:'value', splitLine:{lineStyle:{color:'rgba(36,52,71,0.5)'}}, axisLabel:{color:'#6B7C90'} },
    series: [
      {
        name:'策略权益', type:'line', smooth:true, showSymbol:false, data: equity,
        lineStyle:{ width:2.2, color:'#25D07D' },
        areaStyle:{ color: new echarts.graphic.LinearGradient(0,0,0,1,[
          {offset:0, color:'rgba(37,208,125,0.25)'}, {offset:1, color:'rgba(37,208,125,0)'}]) },
      },
      {
        name:'BTC买入持有', type:'line', smooth:true, showSymbol:false, data: btc,
        lineStyle:{ width:1.5, color:'#F7931A', type:'dashed' },
      },
    ],
  }
})

const statusColor = (s) => ['info','warning','success','danger'][s]
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/backtests`, { page_size: 20 })
    list.value = r.items || []
    if (list.value.length) current.value = list.value[0]
  } catch (e) {
    console.warn('[Backtest] 加载失败:', e)
  } finally {
    loading.value = false
  }
}
const submit = async () => {
  if (!form.range || !form.range.length) return ElMessage.warning('请选择回测日期')
  try {
    await http.post(`${API_PREFIX}/backtests`, {
      strategy_id: form.strategy_id,
      run_name: form.run_name || `回测-${new Date().toLocaleString().slice(0,10)}`,
      symbols: form.symbols,
      timeframe: form.timeframe,
      date_start: form.range[0],
      date_end: form.range[1],
      initial_capital: form.initial_capital,
      fee_rate: form.fee_rate,
      slippage: form.slippage,
      strategy_params: {},
    })
    ElMessage.success('回测任务已提交（后台异步执行，请刷新查看进度）')
    showCreate.value = false
    load()
  } catch (e) {
    ElMessage.error(e?.message || '回测任务提交失败')
  }
}
const view = (row) => { current.value = row }
const clone = (row) => {
  Object.assign(form, { symbols: row.symbols, timeframe: row.timeframe, strategy_id: row.strategy_id })
  form.run_name = row.run_name + ' - 副本'
  showCreate.value = true
}
const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`删除回测 ${row.run_name}？`, '确认', { type: 'warning' })
    await http.delete(`${API_PREFIX}/backtests/${row.id}`)
    ElMessage.success('删除成功')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}

onMounted(load)
</script>

<style lang="scss" scoped>
.mini-metric {
  background: #0C151D;
  border: 1px solid #1E2E41;
  border-radius: 10px;
  padding: 12px 14px;
  .unit { font-size: 12px; font-weight: 400; opacity: 0.75; margin-left: 3px; }
}
</style>
