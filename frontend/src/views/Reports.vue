<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Document /></el-icon>财务报表中心</h2>
        <div class="page-subtitle">日/周/月财务报表 · 盈亏比深度分析 · 一键导出Excel/PDF</div>
      </div>
      <div class="flex gap-12">
        <el-date-picker v-model="range" type="daterange" start-placeholder="开始" end-placeholder="结束" />
        <el-select v-model="account_id" placeholder="选择子账号" clearable style="width:220px;">
          <el-option label="全部子账号汇总" :value="''" />
          <el-option label="币安-主策略子账号" :value="1" />
          <el-option label="OKX-黄金石油子账号" :value="2" />
        </el-select>
        <el-button :icon="Download" type="success">导出 Excel</el-button>
        <el-button :icon="Printer" type="warning">打印 / PDF</el-button>
      </div>
    </div>

    <!-- 聚合统计卡 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="4" v-for="m in summaryList" :key="m.key">
        <div class="stat-card">
          <div class="stat-card__label">
            <span style="display:flex;align-items:center;gap:4px;">
              <span class="status-light" :class="m.lightStatus || 'ok'"></span>
              {{ m.label }}
            </span>
          </div>
          <div class="stat-card__value" :class="m.cls">
            <span v-if="m.money">$</span>{{ m.value }}<span v-if="m.pct">%</span>
          </div>
          <div class="stat-card__extra text-dim">{{ m.sub }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb-16">
      <!-- 图表切换：日盈亏柱状 / 权益曲线 / 品种热力图 -->
      <el-col :span="16">
        <div class="panel-card" style="height: 420px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#25D07D"><TrendCharts /></el-icon>
              财务趋势
            </span>
            <el-radio-group v-model="chartType" size="small">
              <el-radio-button value="daily">日盈亏柱</el-radio-button>
              <el-radio-button value="equity">权益曲线</el-radio-button>
              <el-radio-button value="symbol">品种收益</el-radio-button>
            </el-radio-group>
          </div>
          <div class="panel-card__body" style="height: calc(100% - 56px);">
            <v-chart :option="chart" autoresize style="height: 100%;" />
          </div>
        </div>
      </el-col>
      <!-- 维度分析 -->
      <el-col :span="8">
        <div class="panel-card" style="height: 420px;">
          <div class="panel-card__header"><span class="panel-card__title">分维度胜率/盈亏比</span></div>
          <div class="panel-card__body" style="height: calc(100% - 56px); overflow: auto;">
            <el-table size="small" :header-cell-style="{ background:'#192738' }">
              <el-table-column label="维度" width="80" fixed />
              <el-table-column prop="item" label="项" width="90" />
              <el-table-column label="笔数" width="60" align="right">
                <template #default="{ row }"><span class="monospace">{{ row.count }}</span></template>
              </el-table-column>
              <el-table-column label="胜率" width="70" align="right">
                <template #default="{ row }">
                  <span :class="row.win_rate>=50?'text-profit':'text-loss'">{{ row.win_rate }}%</span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏比" width="70" align="right">
                <template #default="{ row }">
                  <span :class="row.pf>=2?'text-profit':'text-warn'">{{ row.pf }}</span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏($)" width="90" align="right">
                <template #default="{ row }">
                  <span class="monospace" :class="fmtPnlClass(row.pnl)">{{ Number(row.pnl)>=0?'+':'' }}{{ fmtMoney(row.pnl) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 报表Tabs -->
    <div class="panel-card">
      <el-tabs v-model="tab" type="card">
        <el-tab-pane label="日报表" name="daily">
          <el-table :data="dailyRows" stripe v-loading="tab==='daily'&&loading" :header-cell-style="{ background:'#192738' }">
            <el-table-column label="日期" prop="report_date" width="120" fixed />
            <el-table-column label="期初权益" align="right">
              <template #default="{ row }"><span class="monospace">${{ fmtMoney(row.start_balance) }}</span></template>
            </el-table-column>
            <el-table-column label="期末权益" align="right">
              <template #default="{ row }"><span class="monospace text-strong">${{ fmtMoney(row.end_balance) }}</span></template>
            </el-table-column>
            <el-table-column label="当日盈亏" align="right" width="140">
              <template #default="{ row }">
                <span class="monospace" :class="fmtPnlClass(row.total_pnl)" style="font-weight:600;">
                  {{ Number(row.total_pnl)>=0?'+':'' }}${{ fmtMoney(row.total_pnl) }}
                  <span class="text-dim" style="margin-left:6px; font-weight:400;">
                    ({{ Number(row.total_pnl_pct)>=0?'+':'' }}{{ Number(row.total_pnl_pct).toFixed(2) }}%)
                  </span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="交易笔数" width="100" align="center">
              <template #default="{ row }">{{ row.trade_count }}</template>
            </el-table-column>
            <el-table-column label="胜率" width="100" align="center">
              <template #default="{ row }">
                <span style="display:inline-flex;align-items:center;gap:4px;">
                  <span class="status-light" :class="row.win_rate>=50?'ok':'error'"></span>
                  <el-tag size="small" :type="row.win_rate>=50?'success':'danger'" effect="plain">{{ row.win_rate }}%</el-tag>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="盈亏比" width="90" align="center">
              <template #default="{ row }">{{ row.profit_factor }}</template>
            </el-table-column>
            <el-table-column label="当日最大回撤" width="130" align="center">
              <template #default="{ row }"><span class="text-loss">-{{ row.max_drawdown_daily }}%</span></template>
            </el-table-column>
            <el-table-column label="风控事件" width="110" align="center">
              <template #default="{ row }">
                <span style="display:inline-flex;align-items:center;gap:4px;">
                  <span class="status-light" :class="row.risk_event_count>0?'error':'ok'"></span>
                  <el-tag size="small" v-if="row.risk_event_count>0" type="danger" effect="plain">{{ row.risk_event_count }}</el-tag>
                  <span v-else class="text-dim">0</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="手续费" width="110" align="right">
              <template #default="{ row }"><span class="monospace text-dim">${{ fmtMoney(row.fee_total) }}</span></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="周报表" name="weekly">
          <el-table :data="weeklyRows" stripe v-loading="tab==='weekly'&&loading" :header-cell-style="{ background:'#192738' }">
            <el-table-column label="周次" prop="week_key" width="130" fixed />
            <el-table-column label="区间" width="240">
              <template #default="{ row }">{{ row.week_start }} ~ {{ row.week_end }}</template>
            </el-table-column>
            <el-table-column label="周收益" width="140" align="right">
              <template #default="{ row }">
                <span class="monospace" :class="fmtPnlClass(row.total_pnl)" style="font-weight:600;">
                  {{ Number(row.total_pnl)>=0?'+':'' }}${{ fmtMoney(row.total_pnl) }}
                  <span class="text-dim" style="font-weight:400; margin-left:6px;">({{ Number(row.total_pnl_pct)>=0?'+':'' }}{{ Number(row.total_pnl_pct).toFixed(2) }}%)</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="夏普比率" width="100" align="center">
              <template #default="{ row }">{{ Number(row.sharpe_ratio||0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="最大回撤" width="120" align="center">
              <template #default="{ row }"><span class="text-loss">-{{ Number(row.max_drawdown_pct||0).toFixed(2) }}%</span></template>
            </el-table-column>
            <el-table-column label="交易数" width="90" align="center" prop="total_trade_count" />
            <el-table-column label="胜率" width="90" align="center">
              <template #default="{ row }">{{ Number(row.win_rate||0).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="盈亏比" width="90" align="center">
              <template #default="{ row }">{{ Number(row.profit_factor||0).toFixed(2) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="月报表" name="monthly">
          <el-table :data="monthlyRows" stripe v-loading="tab==='monthly'&&loading" :header-cell-style="{ background:'#192738' }">
            <el-table-column label="月份" prop="month_key" width="110" fixed />
            <el-table-column label="期初→期末" width="260">
              <template #default="{ row }">
                <span class="monospace">${{ fmtMoney(row.start_balance) }}</span>
                <span class="text-dim" style="margin: 0 6px;">→</span>
                <span class="monospace text-strong">${{ fmtMoney(row.end_balance) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="月收益率" width="130" align="right">
              <template #default="{ row }">
                <span class="monospace" :class="fmtPnlClass(row.total_pnl)" style="font-weight:700; font-size:14px;">
                  {{ Number(row.total_pnl_pct)>=0?'+':'' }}{{ Number(row.total_pnl_pct).toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="对比BTC" width="110" align="center">
              <template #default="{ row }">
                <span :class="Number(row.total_pnl_pct) > Number(row.btc_benchmark_pct||0)?'text-profit':'text-loss'">
                  {{ Number(row.total_pnl_pct) - Number(row.btc_benchmark_pct||0) >= 0 ? '+' : '' }}
                  {{ (Number(row.total_pnl_pct) - Number(row.btc_benchmark_pct||0)).toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="对比ETH" width="110" align="center">
              <template #default="{ row }">
                <span :class="Number(row.total_pnl_pct) > Number(row.eth_benchmark_pct||0)?'text-profit':'text-loss'">
                  {{ Number(row.total_pnl_pct) - Number(row.eth_benchmark_pct||0) >= 0 ? '+' : '' }}
                  {{ (Number(row.total_pnl_pct) - Number(row.eth_benchmark_pct||0)).toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="夏普" width="80" align="center"><template #default="{row}">{{ Number(row.sharpe_ratio||0).toFixed(2) }}</template></el-table-column>
            <el-table-column label="最大回撤" width="110" align="center">
              <template #default="{ row }"><span class="text-loss">-{{ Number(row.max_drawdown_pct||0).toFixed(2) }}%</span></template>
            </el-table-column>
            <el-table-column label="卡玛比率" width="100" align="center"><template #default="{row}">{{ Number(row.calmar_ratio||0).toFixed(2) }}</template></el-table-column>
            <el-table-column label="交易数" width="90" align="center" prop="total_trade_count" />
            <el-table-column label="胜率" width="90" align="center">
              <template #default="{ row }">{{ Number(row.win_rate||0).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="最佳连胜" width="100" align="center">
              <template #default="{ row }"><span class="text-profit">{{ row.win_streak_best }}</span></template>
            </el-table-column>
            <el-table-column label="最差连败" width="100" align="center">
              <template #default="{ row }"><span class="text-loss">{{ row.loss_streak_worst }}</span></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
// 统一使用全量 echarts：避免 vue-echarts + echarts/core 按需注册触发
// "registers.registerChartView is not a function"（同 Dashboard 根因）
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Document, Download, Printer, TrendCharts } from '@element-plus/icons-vue'
import { fmtMoney, fmtPnlClass } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const tab = ref('daily')
const loading = ref(true)
const range = ref([])
const account_id = ref(null)
const chartType = ref('daily')

const summaryList = computed(() => [
  { key:'pnl',    label:'区间总盈亏', value:'12,846.25', money:true, cls:'text-profit', sub:'较基准BTC +5,230 USDT', lightStatus:'ok' },
  { key:'wr',     label:'综合胜率',     value:'62.3',     pct:true,   cls:'text-profit', sub:'目标 ≥ 55% ✓', lightStatus:'ok' },
  { key:'pf',     label:'整体盈亏比',   value:'2.14',                cls:'text-info',   sub:'≥2:1 合格 ✓', lightStatus:'ok' },
  { key:'mdd',    label:'最大回撤',     value:'8.6',      pct:true,   cls:'text-loss',   sub:'可容忍上限 15%', lightStatus:'warn' },
  { key:'count',  label:'交易总笔数',   value:'1,256',               cls:'text-strong', sub:'今日 5 / 本月 84', lightStatus:'ok' },
])

const dailyRows = ref([
  { report_date:'2024-08-01', start_balance:101091, end_balance:102348, total_pnl:1256.8, total_pnl_pct:1.24, trade_count:5, win_rate:60, profit_factor:2.1, max_drawdown_daily:1.8, risk_event_count:1, fee_total:14.2 },
  { report_date:'2024-07-31', start_balance:99820,  end_balance:101091, total_pnl:1271.3, total_pnl_pct:1.27, trade_count:7, win_rate:71, profit_factor:2.6, max_drawdown_daily:2.2, risk_event_count:0, fee_total:18.6 },
  { report_date:'2024-07-30', start_balance:100150, end_balance:99820,  total_pnl:-330.1, total_pnl_pct:-0.33, trade_count:4, win_rate:50, profit_factor:0.8, max_drawdown_daily:1.2, risk_event_count:0, fee_total:9.8 },
  { report_date:'2024-07-29', start_balance:98940,  end_balance:100150, total_pnl:1210.4, total_pnl_pct:1.22, trade_count:6, win_rate:67, profit_factor:2.4, max_drawdown_daily:1.6, risk_event_count:0, fee_total:15.3 },
  { report_date:'2024-07-28', start_balance:98200,  end_balance:98940,  total_pnl:740.6,  total_pnl_pct:0.75, trade_count:3, win_rate:66, profit_factor:1.9, max_drawdown_daily:0.9, risk_event_count:0, fee_total:7.6 },
])
const weeklyRows = ref([
  { week_key:'2024-W31', week_start:'07-29', week_end:'08-04', total_pnl:3220.5, total_pnl_pct:3.26, sharpe_ratio:2.1, max_drawdown_pct:2.4, total_trade_count:25, win_rate:64, profit_factor:2.2 },
  { week_key:'2024-W30', week_start:'07-22', week_end:'07-28', total_pnl:2860.8, total_pnl_pct:2.98, sharpe_ratio:1.9, max_drawdown_pct:3.1, total_trade_count:33, win_rate:61, profit_factor:2.0 },
  { week_key:'2024-W29', week_start:'07-15', week_end:'07-21', total_pnl:-680.2, total_pnl_pct:-0.70, sharpe_ratio:-0.3, max_drawdown_pct:4.5, total_trade_count:28, win_rate:46, profit_factor:0.9 },
  { week_key:'2024-W28', week_start:'07-08', week_end:'07-14', total_pnl:4210.5, total_pnl_pct:4.52, sharpe_ratio:2.8, max_drawdown_pct:1.8, total_trade_count:36, win_rate:72, profit_factor:3.1 },
])
const monthlyRows = ref([
  { month_key:'2024-07', start_balance:92000, end_balance:102348, total_pnl:10348, total_pnl_pct:11.25, btc_benchmark_pct:6.4, eth_benchmark_pct:8.1, sharpe_ratio:2.15, max_drawdown_pct:6.8, calmar_ratio:1.65, total_trade_count:122, win_rate:63.8, win_streak_best:8, loss_streak_worst:4 },
  { month_key:'2024-06', start_balance:85500, end_balance:92000, total_pnl:6500, total_pnl_pct:7.60, btc_benchmark_pct:9.8, eth_benchmark_pct:12.3, sharpe_ratio:1.48, max_drawdown_pct:8.2, calmar_ratio:0.93, total_trade_count:98, win_rate:58.2, win_streak_best:6, loss_streak_worst:5 },
  { month_key:'2024-05', start_balance:80000, end_balance:85500, total_pnl:5500, total_pnl_pct:6.88, btc_benchmark_pct:-2.1, eth_benchmark_pct:1.4, sharpe_ratio:1.72, max_drawdown_pct:5.6, calmar_ratio:1.23, total_trade_count:110, win_rate:61.0, win_streak_best:7, loss_streak_worst:3 },
  { month_key:'2024-04', start_balance:76800, end_balance:80000, total_pnl:3200, total_pnl_pct:4.17, btc_benchmark_pct:3.2, eth_benchmark_pct:5.6, sharpe_ratio:1.15, max_drawdown_pct:5.9, calmar_ratio:0.71, total_trade_count:89, win_rate:55.1, win_streak_best:5, loss_streak_worst:6 },
])

const chart = computed(() => {
  const dates = dailyRows.value.map(r => r.report_date.slice(5))
  const dayPnl = dailyRows.value.map(r => Number(r.total_pnl))
  const equity = []; let acc = dailyRows.value[0]?.start_balance || 100000
  dailyRows.value.forEach(r => { equity.push(acc); acc += r.total_pnl })
  const symbolData = [
    { name:'BTC', value: 4230.5, count: 312, wr: 68, pf: 2.8 },
    { name:'ETH', value: 2980.2, count: 288, wr: 62, pf: 2.2 },
    { name:'SOL', value: 1520.8, count: 236, wr: 58, pf: 1.8 },
    { name:'XAU', value: 680.4,  count: 124, wr: 65, pf: 2.1 },
    { name:'WTI', value: -260.0, count: 96,  wr: 42, pf: 0.9 },
    { name:'SAND', value: 0,      count: 0,   wr: 0,  pf: 0   },
    { name:'HBAR', value: 0,      count: 0,   wr: 0,  pf: 0   },
  ]
  if (chartType.value === 'daily') {
    return {
      backgroundColor:'transparent',
      grid:{ left:48, right:20, top:30, bottom:30 },
      tooltip:{ trigger:'axis', backgroundColor:'#1A2B3C', borderColor:'#29405A', textStyle:{color:'#D8E2EC'} },
      xAxis:{ type:'category', data: dates, axisLine:{lineStyle:{color:'#243447'}}, axisLabel:{color:'#6B7C90'} },
      yAxis:{ type:'value', name:'盈亏($)', axisLabel:{color:'#6B7C90'}, splitLine:{lineStyle:{color:'rgba(36,52,71,0.5)'}} },
      series:[{
        type:'bar', data: dayPnl, barWidth: 22,
        itemStyle:{
          borderRadius:[6,6,0,0],
          color:(p)=>p.value>=0?'rgba(74,222,128,0.85)':'rgba(248,113,113,0.85)',
        },
        label:{ show:true, position:'top', color:'#97A6B6', fontSize:11, formatter:(p)=>`${p.value>=0?'+':''}${p.value.toFixed(0)}`},
      }],
    }
  }
  if (chartType.value === 'equity') {
    return {
      backgroundColor:'transparent',
      grid:{ left:56, right:20, top:30, bottom:30 },
      tooltip:{ trigger:'axis', backgroundColor:'#1A2B3C', borderColor:'#29405A', textStyle:{color:'#D8E2EC'}, formatter:(p)=>`${p[0].name}<br/>权益: $${p[0].value.toLocaleString()}` },
      xAxis:{ type:'category', data: dates, boundaryGap:false, axisLine:{lineStyle:{color:'#243447'}}, axisLabel:{color:'#6B7C90'} },
      yAxis:{ type:'value', name:'权益($)', axisLabel:{color:'#6B7C90'}, splitLine:{lineStyle:{color:'rgba(36,52,71,0.5)'}} },
      series:[{
        type:'line', smooth:true, data: equity, showSymbol:false,
        lineStyle:{width:2.5, color:'#25D07D', shadowBlur:10, shadowColor:'rgba(37,208,125,0.4)'},
        areaStyle:{ color: new echarts.graphic.LinearGradient(0,0,0,1,[
          {offset:0, color:'rgba(37,208,125,0.28)'}, {offset:1, color:'rgba(37,208,125,0)'}]) },
        markLine:{ silent:true, symbol:'none', lineStyle:{color:'#FBBF24', type:'dashed'}, data:[{yAxis: dailyRows.value[0]?.start_balance, label:{formatter:'期初', color:'#FBBF24'}}] },
      }],
    }
  }
  // symbol pie
  return {
    backgroundColor:'transparent',
    tooltip:{ trigger:'item', backgroundColor:'#1A2B3C', borderColor:'#29405A', textStyle:{color:'#D8E2EC'} },
    legend:{ bottom: 0, textStyle:{ color:'#97A6B6' } },
    series:[{
      type:'pie', radius:['45%','72%'], center:['50%','46%'],
      itemStyle:{ borderColor:'#152330', borderWidth:3, borderRadius:4 },
      label:{ color:'#D8E2EC', formatter:'{b}\n{d}%' },
      labelLine:{ lineStyle:{color:'#29405A'} },
      data: symbolData.map(x=>({
        name:`${x.name} $${x.value>=0?'+':''}${x.value.toFixed(0)}`,
        value: Math.abs(x.value),
        itemStyle:{ color: x.value>=0 ? ['#F7931A','#627EEA','#9945FF','#FBBF24','#6B7280'][symbolData.indexOf(x)] : '#F87171' },
      })),
    }],
  }
})

const load = async () => {
  loading.value = true
  try {
    if (tab.value === 'daily') {
      const r = await http.get(`${API_PREFIX}/reports/daily`, {
        account_id: account_id.value,
        start_date: range.value?.[0], end_date: range.value?.[1],
        page_size: 60,
      })
      if (r.items?.length) dailyRows.value = r.items
    } else if (tab.value === 'weekly') {
      const r = await http.get(`${API_PREFIX}/reports/weekly`, {
        account_id: account_id.value,
        page_size: 52,
      })
      if (r.items?.length) weeklyRows.value = r.items
    } else if (tab.value === 'monthly') {
      const r = await http.get(`${API_PREFIX}/reports/monthly`, {
        account_id: account_id.value,
        page_size: 24,
      })
      if (r.items?.length) monthlyRows.value = r.items
    }
  } catch (e) {
    console.warn('[Reports] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

watch(tab, () => load())

onMounted(load)
</script>
