<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Warning /></el-icon>风控中心</h2>
        <div class="page-subtitle">实时监控账户风险，处理单笔回撤、日亏损、连续亏损等风控事件</div>
      </div>
      <el-button :icon="RefreshRight" @click="load">刷新</el-button>
    </div>

    <!-- 风控总览 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="4" v-for="k in kpiList" :key="k.key">
        <div class="stat-card risk-card" :class="k.cls">
          <div class="stat-card__label">{{ k.label }}</div>
          <div class="stat-card__value" :class="k.valueCls">
            <span v-if="k.isPct">%</span>{{ k.value }}
          </div>
          <div class="stat-card__extra text-dim">{{ k.desc }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 风控规则配置 -->
      <el-col :span="10">
        <div class="panel-card mb-16">
          <div class="panel-card__header"><span class="panel-card__title">风控规则配置</span></div>
          <div class="panel-card__body">
            <el-form label-width="160px">
              <el-form-item label="单笔最大回撤">
                <el-input-number v-model="cfg.single_dd" :min="0.1" :max="30" :step="0.5" :precision="1" />
                <span class="text-dim" style="margin-left:10px;">% 账户权益</span>
              </el-form-item>
              <el-form-item label="每日最大亏损">
                <el-input-number v-model="cfg.daily_loss" :min="0.5" :max="50" :step="0.5" :precision="1" />
                <span class="text-dim" style="margin-left:10px;">% 账户权益，达阈值当日停止交易</span>
              </el-form-item>
              <el-form-item label="总仓位上限">
                <el-input-number v-model="cfg.total_pos" :min="10" :max="100" :step="5" />
                <span class="text-dim" style="margin-left:10px;">% 账户权益</span>
              </el-form-item>
              <el-form-item label="最大同时持仓">
                <el-input-number v-model="cfg.max_pos_count" :min="1" :max="20" /> 笔
              </el-form-item>
              <el-form-item label="连续亏损冷静期">
                <el-input-number v-model="cfg.loss_streak" :min="1" :max="20" /> 单 → 暂停
                <el-input-number v-model="cfg.cooldown_h" :min="1" :max="168" style="margin-left:10px;" /> 小时
              </el-form-item>
              <el-form-item label="最低开仓评分">
                <el-slider v-model="cfg.score_min" :min="0" :max="10" :step="0.5" show-stops show-input />
              </el-form-item>
              <el-form-item label="强信号评分(激进杠杆)">
                <el-slider v-model="cfg.score_strong" :min="5" :max="10" :step="0.5" show-stops show-input />
              </el-form-item>
              <el-form-item label="杠杆允许区间">
                <el-slider v-model="cfg.lev_range" range :min="1" :max="20" :marks="{3:'3x',5:'5x',10:'10x',20:'20x'}" />
              </el-form-item>
              <el-form-item label="默认止盈止损比">
                <el-input-number v-model="cfg.tp_sl_ratio" :min="1" :max="10" :step="0.1" /> : 1
              </el-form-item>
              <div class="flex justify-end">
                <el-button type="primary" @click="saveCfg">保存风控配置</el-button>
              </div>
            </el-form>
          </div>
        </div>
      </el-col>

      <!-- 风控事件日志 -->
      <el-col :span="14">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">风控事件日志</span>
            <div class="flex gap-8">
              <el-select v-model="f.severity" placeholder="严重程度" clearable size="small" style="width:120px;">
                <el-option label="提醒" :value="1" />
                <el-option label="警告" :value="2" />
                <el-option label="危险" :value="3" />
              </el-select>
              <el-select v-model="f.type" placeholder="事件类型" clearable size="small" style="width:160px;">
                <el-option label="单笔回撤超限" :value="1" />
                <el-option label="日亏损超限" :value="2" />
                <el-option label="连续亏损" :value="3" />
                <el-option label="持仓超限" :value="4" />
                <el-option label="API异常" :value="5" />
                <el-option label="异常行情" :value="6" />
                <el-option label="强制平仓" :value="7" />
              </el-select>
            </div>
          </div>
          <div class="panel-card__body" style="padding: 0;">
            <el-table :data="events" v-loading="loading" :header-cell-style="{ background:'#192738' }">
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ row.created_at }}</template>
              </el-table-column>
              <el-table-column label="严重度" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="['info','warning','danger'][row.severity-1]" effect="dark" round>
                    {{ ['提醒','警告','危险'][row.severity-1] }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="130">
                <template #default="{ row }">
                  {{ ['','单笔回撤','日亏损','连续亏损','持仓超限','API异常','异常行情','强平','冷静期开始','冷静期结束'][row.event_type] || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="标题" min-width="200">
                <template #default="{ row }"><span class="text-strong">{{ row.title }}</span></template>
              </el-table-column>
              <el-table-column label="详情" min-width="260">
                <template #default="{ row }">
                  <span class="text-dim">{{ row.detail }}</span>
                </template>
              </el-table-column>
              <el-table-column label="品种/订单" width="130">
                <template #default="{ row }">
                  <el-tag size="small" v-if="row.symbol" effect="plain">{{ row.symbol }}</el-tag>
                  <span v-else class="text-dim">—</span>
                </template>
              </el-table-column>
              <el-table-column label="处置" width="110" align="center">
                <template #default="{ row }">
                  {{ ['记录','撤单','平仓','暂停策略'][row.action_taken] || '仅记录' }}
                  <el-tag v-if="row.notified" size="small" type="success" effect="plain" style="margin-left:4px;">已通知</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Warning, RefreshRight } from '@element-plus/icons-vue'
import { http, API_PREFIX } from '@/utils/request'

const cfg = reactive({
  single_dd: 2, daily_loss: 5, total_pos: 50, max_pos_count: 3,
  loss_streak: 3, cooldown_h: 24, score_min: 5, score_strong: 8,
  lev_range: [3, 10], tp_sl_ratio: 2,
})
const f = reactive({ severity: undefined, type: undefined })
const events = ref([])
const loading = ref(true)

const kpiList = computed(() => [
  { key:'cur-dd',   label:'当前账户回撤',   value:'3.2',  isPct:true, cls:'r2', valueCls:'text-warn',   desc:'近30天峰值 vs 当前' },
  { key:'daily',    label:'今日已实现盈亏', value:'+1,256', isPct:false, cls:'r1', valueCls:'text-profit', desc:'距离日亏损上限 -3.74%' },
  { key:'position', label:'当前仓位使用率', value:'32',  isPct:true, cls:'r1', valueCls:'text-info',   desc:'上限 50%，安全' },
  { key:'streak',   label:'连续亏损单数',   value:'1',   isPct:false, cls:'r1', valueCls:'text-strong', desc:'上限 3 单触发冷静期' },
])

const saveCfg = async () => {
  ElMessage.success('风控配置已保存（生产请持久化到配置表）')
}
const load = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/risk/events`, { ...f, page_size: 30 })
    events.value = r.items || []
  } catch (e) {
    console.warn('[Risk] 事件加载失败:', e)
  } finally {
    loading.value = false
  }
  if (!events.value.length) {
    events.value = [
      { created_at: '2024-08-01 14:22:08', severity: 3, event_type: 7, title: '强平触发', detail: 'BTC多单 单笔回撤达2.1%，强制平仓', symbol: 'BTC', action_taken: 2, notified: true },
      { created_at: '2024-08-01 11:08:12', severity: 2, event_type: 1, title: '单笔回撤预警', detail: 'SOL多单已回撤1.6%，接近上限2%', symbol: 'SOL', action_taken: 0, notified: true },
      { created_at: '2024-07-31 22:41:00', severity: 2, event_type: 3, title: '连续亏损2单', detail: '连续亏损单数达到2/3', symbol: '', action_taken: 0, notified: true },
      { created_at: '2024-07-31 16:30:20', severity: 1, event_type: 4, title: '持仓数达到上限', detail: '同时持有3个仓位（上限=3），新单被拦截', symbol: '', action_taken: 3, notified: false },
      { created_at: '2024-07-30 09:15:54', severity: 3, event_type: 5, title: '交易所API异常', detail: '币安接口连续失败6次，熔断30分钟', symbol: '', action_taken: 3, notified: true },
    ]
  }
}
onMounted(load)
</script>

<style lang="scss" scoped>
.risk-card.r1 { border-top: 3px solid #4ADE80; }
.risk-card.r2 { border-top: 3px solid #FBBF24; }
.risk-card.r3 { border-top: 3px solid #F87171; }
.risk-card.r4 { border-top: 3px solid #60A5FA; }
.justify-end { justify-content: flex-end; }
</style>
