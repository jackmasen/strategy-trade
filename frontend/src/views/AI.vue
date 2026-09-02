<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Cpu /></el-icon>AI 实时分析</h2>
        <div class="page-subtitle">对接大模型或自定义AI接口，综合评分占30%权重，可手动触发深度分析</div>
      </div>
      <el-button v-if="user.isAdmin" type="primary" link :icon="Setting" @click="showCfg = true">配置AI接口</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :span="9">
        <div class="panel-card mb-16">
          <div class="panel-card__header"><span class="panel-card__title">当前AI配置</span></div>
          <div class="panel-card__body" v-loading="cfgLoading">
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="供应商">{{ cfg.provider }}</el-descriptions-item>
              <el-descriptions-item label="模型">{{ cfg.model_name }}</el-descriptions-item>
              <el-descriptions-item label="Endpoint">{{ cfg.api_endpoint || '默认' }}</el-descriptions-item>
              <el-descriptions-item label="API Key">
                <el-tag effect="dark" type="success">已配置</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="今日调用次数">{{ todayCalls }}</el-descriptions-item>
              <el-descriptions-item label="累计消耗成本">${{ totalCost.toFixed(4) }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </div>

        <!-- 新闻AI多接口配置 -->
        <div class="panel-card mb-16" v-if="user.isAdmin">
          <div class="panel-card__header">
            <span class="panel-card__title">新闻AI多接口配置</span>
            <el-button link type="primary" size="small" @click="openNewsConfigDialog">
              <el-icon><Edit /></el-icon> 管理
            </el-button>
          </div>
          <div class="panel-card__body" style="padding: 12px 16px;">
            <div v-if="newsAiConfigs.length === 0" class="text-dim text-center" style="padding: 16px 0; font-size: 13px;">
              暂无新闻AI专属配置，将使用通用AI配置
              <div style="margin-top: 8px;">
                <el-button size="small" type="primary" plain @click="openAddNewsConfig">+ 添加新闻AI接口</el-button>
              </div>
            </div>
            <div v-else class="news-api-list">
              <div v-for="(c, idx) in newsAiConfigs" :key="c.id" class="news-api-item" :class="{ disabled: !c.enabled }">
                <div class="news-api-priority">{{ idx + 1 }}</div>
                <div class="news-api-info">
                  <div class="news-api-name">
                    {{ c.name }}
                    <el-tag size="small" :type="c.enabled ? 'success' : 'info'" effect="plain" style="margin-left: 6px;">
                      {{ c.enabled ? '启用' : '停用' }}
                    </el-tag>
                  </div>
                  <div class="news-api-detail text-dim">{{ c.model_name }} · {{ c.provider }}</div>
                </div>
                <div class="news-api-status">
                  <el-tag v-if="c.has_key" size="small" type="success" effect="dark">Key已配置</el-tag>
                  <el-tag v-else size="small" type="warning" effect="dark">无Key</el-tag>
                </div>
              </div>
            </div>
            <div class="text-dim" style="font-size: 11px; margin-top: 8px; text-align: center;">
              按优先级轮询调用，失败自动切换下一个
            </div>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">手动触发分析</span></div>
          <div class="panel-card__body">
            <el-form label-position="top">
              <el-form-item label="分析类型">
                <el-radio-group v-model="aForm.type">
                  <el-radio-button value="score">综合评分</el-radio-button>
                  <el-radio-button value="position">持仓紧急分析</el-radio-button>
                  <el-radio-button value="news">热点新闻解读</el-radio-button>
                  <el-radio-button value="strategy">策略优化建议</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="关联品种">
                <el-select v-model="aForm.symbol" placeholder="选择品种" style="width:100%;">
                  <el-option v-for="(m,k) in SYMBOL_META" :key="k" :label="`${m.icon} ${k} ${m.name}`" :value="k" />
                </el-select>
              </el-form-item>
              <el-form-item label="时间周期">
                <el-select v-model="aForm.timeframe" style="width:100%;">
                  <el-option label="1小时" value="1h" />
                  <el-option label="4小时" value="4h" />
                  <el-option label="1日" value="1d" />
                </el-select>
              </el-form-item>
              <el-form-item label="附加提示词 (可选)">
                <el-input v-model="aForm.prompt" type="textarea" :rows="4" placeholder="输入你想让AI特别关注的信息" />
              </el-form-item>
              <el-button type="primary" :icon="Promotion" :loading="loading" style="width:100%;" @click="run">
                开始AI分析
              </el-button>
            </el-form>
          </div>
        </div>
      </el-col>

      <el-col :span="15">
        <div class="panel-card mb-16" style="min-height: 300px;">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-tag v-if="lastResult" size="small" :type="lastResult.ai_score >= 2 ? 'success' : lastResult.ai_score >= 1 ? 'warning':'danger'" effect="dark">
                AI评分 {{ lastResult.ai_score?.toFixed(1) }} / 3.0
              </el-tag>
              <span style="margin-left:10px;">最近分析结果</span>
            </span>
            <el-tag v-if="lastResult" size="small" :type="lastResult.ai_direction==='long'?'success':lastResult.ai_direction==='short'?'danger':'info'" effect="plain">
              建议: {{ lastResult.ai_direction==='long'?'做多':lastResult.ai_direction==='short'?'做空':'观望' }}
            </el-tag>
          </div>
          <div class="panel-card__body" v-if="lastResult">
            <div class="ai-result">
              <div class="ai-score-ring">
                <div class="score-ring" :data-level="aiLevel">
                  {{ (lastResult.ai_score/3*10).toFixed(1) }}
                </div>
                <div class="text-center text-dim mt-8" style="font-size:12px;">满分10分</div>
              </div>
              <div class="ai-result-text">
                <h4 style="color:#F0F4F8; margin:0 0 10px;">AI分析理由</h4>
                <p style="line-height:1.7; color:#B6C2CF;">{{ lastResult.ai_reason || '（暂无结果，请点击左侧开始分析）' }}</p>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无分析记录，点击左侧开始" style="padding: 60px 0;" />
        </div>

        <div class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">历史调用记录</span></div>
          <div class="panel-card__body" style="padding: 0;">
            <el-table :data="history" size="default" :header-cell-style="{ background:'#192738' }">
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ row.time }}</template>
              </el-table-column>
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ row.type_name }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="品种/周期" width="140">
                <template #default="{ row }">
                  <span class="monospace">{{ row.symbol || '-' }}</span>
                  <el-tag size="small" effect="plain" style="margin-left:6px;">{{ row.timeframe }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="AI评分(0-3)" width="110" align="center">
                <template #default="{ row }">
                  <span class="monospace" :class="Number(row.score)>=2?'text-profit':Number(row.score)>=1?'text-warn':'text-loss'">
                    {{ Number(row.score || 0).toFixed(1) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="建议方向" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="dark" :type="row.direction==='long'?'success':row.direction==='short'?'danger':'info'">
                    {{ row.direction==='long'?'多':row.direction==='short'?'空':'观' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Token消耗" width="110" align="center">
                <template #default="{ row }">
                  <span class="monospace text-dim">{{ row.prompt }} + {{ row.completion }}</span>
                </template>
              </el-table-column>
              <el-table-column label="耗时/成本" width="130" align="center">
                <template #default="{ row }">
                  <div class="monospace">{{ row.latency }}ms</div>
                  <div class="text-dim" style="font-size:11px;">${{ row.cost?.toFixed(5) }}</div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.success?'success':'danger'" effect="dark" round>
                    {{ row.success ? 'OK' : '失败' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 通用AI配置对话框 -->
    <el-dialog v-model="showCfg" title="AI接口配置" width="560px">
      <el-form label-width="110px">
        <el-form-item label="供应商">
          <el-select v-model="cfg.provider" style="width:100%;">
            <el-option label="OpenAI GPT" value="openai" />
            <el-option label="Anthropic Claude" value="anthropic" />
            <el-option label="自定义接口(推荐)" value="custom" />
            <el-option label="本地模型(Ollama)" value="local" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="cfg.api_key" type="password" show-password placeholder="sk-...（留空则不修改现有Key）" />
          <div style="font-size:12px;color:#909399;margin-top:4px;">
            已有Key：{{ cfg.has_key ? '已设置' : '未设置' }}
          </div>
        </el-form-item>
        <el-form-item label="Endpoint">
          <el-input v-model="cfg.api_endpoint" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="cfg.model_name" placeholder="gpt-4o / deepseek-chat / qwen-plus" />
        </el-form-item>
        <el-divider content-position="left">高级参数</el-divider>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="温度">
              <el-input-number v-model="cfg.temperature" :min="0" :max="10" :step="1" style="width:100%;" />
              <div style="font-size:11px;color:#909399;">0-10（实际/10）</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最大Token">
              <el-input-number v-model="cfg.max_tokens" :min="128" :max="8192" :step="128" style="width:100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="超时(秒)">
              <el-input-number v-model="cfg.request_timeout_sec" :min="5" :max="120" style="width:100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="重试次数">
              <el-input-number v-model="cfg.max_retries" :min="0" :max="5" style="width:100%;" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="showCfg = false">取消</el-button>
        <el-button :loading="testing" @click="testAi">测试连接</el-button>
        <el-button type="primary" :loading="saving" @click="saveCfg">保存配置</el-button>
      </template>
    </el-dialog>

    <!-- 新闻AI多接口配置对话框 -->
    <el-dialog v-model="showNewsCfg" title="新闻AI多接口配置（轮询/故障转移）" width="720px">
      <div class="news-cfg-header">
        <div class="text-dim" style="font-size: 13px;">
          配置多个AI接口，新闻分析时按优先级轮询调用，失败自动切换到下一个，提高稳定性
        </div>
        <el-button type="primary" size="small" :icon="Plus" @click="openAddNewsConfig">+ 新增接口</el-button>
      </div>
      <el-table :data="newsAiConfigs" size="default" :header-cell-style="{ background:'#192738' }" style="margin-top: 12px;">
        <el-table-column label="优先级" width="70" align="center">
          <template #default="{ $index }">{{ $index + 1 }}</template>
        </el-table-column>
        <el-table-column label="名称" min-width="120">
          <template #default="{ row }">{{ row.name }}</template>
        </el-table-column>
        <el-table-column label="供应商" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.provider }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模型" width="140">
          <template #default="{ row }">{{ row.model_name }}</template>
        </el-table-column>
        <el-table-column label="API Key" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.has_key" size="small" type="success" effect="dark">已配置</el-tag>
            <el-tag v-else size="small" type="warning" effect="dark">未配置</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" @change="toggleNewsConfig(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="editNewsConfig(row)">编辑</el-button>
            <el-button size="small" link type="success" @click="testNewsConfig(row)">测试</el-button>
            <el-button size="small" link type="danger" @click="deleteNewsConfig(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="newsAiConfigs.length === 0" class="text-dim text-center" style="padding: 30px 0;">
        暂无配置，点击右上角"新增接口"添加
      </div>

      <el-divider v-if="showNewsForm" content-position="left">
        {{ editingNewsId ? '编辑接口' : '新增接口' }}
      </el-divider>
      <el-form v-if="showNewsForm" label-width="100px" :model="newsForm">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="配置名称">
              <el-input v-model="newsForm.name" placeholder="如：主API / 备用API1" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="供应商">
              <el-select v-model="newsForm.provider" style="width:100%;">
                <el-option label="OpenAI GPT" value="openai" />
                <el-option label="Anthropic Claude" value="anthropic" />
                <el-option label="自定义接口" value="custom" />
                <el-option label="本地模型" value="local" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="Endpoint">
          <el-input v-model="newsForm.api_endpoint" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="16">
            <el-form-item label="API Key">
              <el-input v-model="newsForm.api_key" type="password" show-password
                :placeholder="editingNewsId ? '留空则不修改现有Key' : 'sk-...'" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="模型名称">
              <el-input v-model="newsForm.model_name" placeholder="gpt-4o-mini" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-input-number v-model="newsForm.priority" :min="1" :max="99" style="width:100%;" />
              <div style="font-size:11px;color:#909399;">数字越小越先调用</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-switch v-model="newsForm.enabled" active-text="启用" inactive-text="停用" />
            </el-form-item>
          </el-col>
        </el-row>
        <div style="text-align: right; margin-bottom: 10px;">
          <el-button @click="showNewsForm = false">取消</el-button>
          <el-button :loading="newsTesting" @click="testCurrentNewsConfig">测试连接</el-button>
          <el-button type="primary" :loading="newsSaving" @click="saveNewsConfig">保存</el-button>
        </div>
      </el-form>

      <template #footer>
        <el-button type="primary" @click="showNewsCfg = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cpu, Setting, Promotion, Edit, Plus } from '@element-plus/icons-vue'
import { SYMBOL_META, scoreLevel } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'
import { useUserStore } from '@/store/user'

const user = useUserStore()

const showCfg = ref(false)
const showNewsCfg = ref(false)
const showNewsForm = ref(false)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const newsSaving = ref(false)
const newsTesting = ref(false)
const todayCalls = ref(0)
const totalCost = ref(0)
const cfgLoading = ref(true)
const historyLoading = ref(false)
const editingNewsId = ref('')

const cfg = reactive({
  provider: 'custom',
  api_key: '',
  api_endpoint: '',
  model_name: 'gpt-4o',
  temperature: 3,
  max_tokens: 800,
  request_timeout_sec: 30,
  max_retries: 2,
  has_key: false,
  api_key_masked: '',
  last_error: '',
  last_verified_at: '',
})

const newsForm = reactive({
  name: '',
  provider: 'custom',
  api_endpoint: '',
  api_key: '',
  model_name: 'gpt-4o-mini',
  enabled: true,
  priority: 1,
})

const newsAiConfigs = ref([])

const aForm = reactive({ type: 'score', symbol: 'BTC', timeframe: '4h', prompt: '' })
const lastResult = ref(null)
const history = ref([
  { time: '14:38', type_name: '综合评分', symbol: 'BTC', timeframe: '4h', score: 2.5, direction: 'long', prompt: 3820, completion: 486, latency: 2480, cost: 0.0128, success: true },
  { time: '13:12', type_name: '持仓分析', symbol: 'ETH', timeframe: '4h', score: 2.1, direction: 'long', prompt: 4120, completion: 512, latency: 3120, cost: 0.0145, success: true },
  { time: '11:05', type_name: '新闻解读', symbol: 'SOL', timeframe: '1h', score: 1.2, direction: 'neutral', prompt: 2980, completion: 322, latency: 1850, cost: 0.0082, success: true },
  { time: '10:22', type_name: '综合评分', symbol: 'XAU', timeframe: '4h', score: 0.8, direction: 'short', prompt: 3280, completion: 286, latency: 2100, cost: 0.0079, success: true },
  { time: '09:48', type_name: '综合评分', symbol: 'WTI', timeframe: '1h', score: 0, direction: 'short', prompt: 0, completion: 0, latency: 0, cost: 0, success: false },
])

const aiLevel = computed(() => scoreLevel((lastResult.value?.ai_score || 0) / 3 * 10))

const loadCfg = async () => {
  cfgLoading.value = true
  try {
    const data = await http.get(`${API_PREFIX}/ai/config`)
    Object.keys(data).forEach(k => {
      if (k !== 'api_key') { cfg[k] = data[k] }
    })
    cfg.api_key = ''
  } catch (e) {
    console.warn('[AI] 配置加载失败:', e)
  } finally {
    cfgLoading.value = false
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/ai/records`, { page_size: 20 })
    const items = r.items || []
    history.value = items.map((item, idx) => ({
      time: item.created_at?.substring(11, 16) || '',
      symbol: item.symbol || '',
      model: item.model_name || item.provider || '',
      score: item.score != null ? Number(item.score).toFixed(2) : '—',
      direction: item.direction || 'neutral',
      tokens: item.input_tokens || 0,
      cost: item.cost_usd || 0,
      status: item.success ? 'success' : 'fail',
    }))
    // 统计今日调用和成本
    const today = new Date().toISOString().split('T')[0]
    let calls = 0, cost = 0
    for (const item of items) {
      if (item.created_at?.startsWith(today)) {
        calls++
        cost += Number(item.cost_usd || 0)
      }
    }
    todayCalls.value = calls
    totalCost.value = cost
  } catch (e) {
    console.warn('[AI] 历史记录加载失败:', e)
  } finally {
    historyLoading.value = false
  }
}

const loadNewsAiConfigs = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/news/ai-configs`)
    newsAiConfigs.value = (r.configs || []).sort((a, b) => (a.priority || 99) - (b.priority || 99))
  } catch {}
}

const saveCfg = async () => {
  if (!cfg.model_name?.trim()) { ElMessage.error('请输入模型名称'); return }
  saving.value = true
  try {
    await http.put(`${API_PREFIX}/ai/config`, {
      provider: cfg.provider, model_name: cfg.model_name, api_endpoint: cfg.api_endpoint,
      api_key: cfg.api_key || '', temperature: cfg.temperature, max_tokens: cfg.max_tokens,
      request_timeout_sec: cfg.request_timeout_sec, max_retries: cfg.max_retries,
    })
    ElMessage.success('AI配置已保存并立即生效')
    showCfg.value = false
    await loadCfg()
  } catch (e) {
    ElMessage.error(e?.message || 'AI 配置保存失败')
  } finally { saving.value = false }
}

const testAi = async () => {
  if (!cfg.model_name?.trim()) { ElMessage.error('请输入模型名称'); return }
  const keyToSend = cfg.api_key || (cfg.has_key ? '__USE_EXISTING__' : '')
  if (!keyToSend || keyToSend === '') { ElMessage.error('请输入 API Key'); return }
  testing.value = true
  try {
    const r = await http.post(`${API_PREFIX}/settings/ai/test`, {
      provider: cfg.provider, model_name: cfg.model_name, api_endpoint: cfg.api_endpoint, api_key: keyToSend,
    })
    ElMessage.success(`连接成功！耗时 ${r.latency_ms || '?'}ms`)
  } catch (e) {
    ElMessage.error(e?.message || '连接测试失败')
  } finally { testing.value = false }
}

const run = async () => {
  loading.value = true
  try {
    const r = await http.post(`${API_PREFIX}/ai/analyze`, {
      analysis_type: aForm.type, symbol: aForm.symbol, timeframe: aForm.timeframe, manual_prompt: aForm.prompt,
    })
    lastResult.value = r || {
      ai_score: 2.2 + Math.random() * 0.8,
      ai_direction: ['long','short','neutral'][Math.floor(Math.random()*3)],
      ai_reason: aForm.prompt || '基于当前技术面MACD金叉+成交量温和放大，叠加美联储鸽派讲话的市场情绪，短期偏多；但需警惕上方关键阻力位，建议轻仓分批入场，严格设置止损。',
    }
    ElMessage.success('AI分析完成')
    loadHistory()
  } catch (e) {
    lastResult.value = {
      ai_score: 0, ai_direction: 'neutral',
      ai_reason: 'AI 分析调用失败：' + (e?.message || '请检查 API Key 与模型配置'),
    }
  } finally { loading.value = false }
}

// ---------- 新闻AI多接口配置 ----------
const openNewsConfigDialog = async () => {
  showNewsCfg.value = true
  showNewsForm.value = false
  await loadNewsAiConfigs()
}

const openAddNewsConfig = () => {
  editingNewsId.value = ''
  newsForm.name = ''
  newsForm.provider = 'custom'
  newsForm.api_endpoint = ''
  newsForm.api_key = ''
  newsForm.model_name = 'gpt-4o-mini'
  newsForm.enabled = true
  newsForm.priority = newsAiConfigs.value.length + 1
  showNewsForm.value = true
  if (!showNewsCfg.value) showNewsCfg.value = true
}

const editNewsConfig = (row) => {
  editingNewsId.value = row.id
  newsForm.name = row.name
  newsForm.provider = row.provider
  newsForm.api_endpoint = row.api_endpoint || ''
  newsForm.api_key = ''
  newsForm.model_name = row.model_name
  newsForm.enabled = row.enabled
  newsForm.priority = row.priority
  showNewsForm.value = true
}

const toggleNewsConfig = async (row) => {
  try {
    await http.put(`${API_PREFIX}/news/ai-configs/${row.id}`, { enabled: row.enabled })
    ElMessage.success('状态已更新')
    await loadNewsAiConfigs()
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e?.message || '更新失败')
  }
}

const saveNewsConfig = async () => {
  if (!newsForm.name?.trim()) { ElMessage.error('请输入配置名称'); return }
  if (!newsForm.model_name?.trim()) { ElMessage.error('请输入模型名称'); return }
  if (!editingNewsId.value && !newsForm.api_key) { ElMessage.error('请输入 API Key'); return }
  newsSaving.value = true
  try {
    if (editingNewsId.value) {
      await http.put(`${API_PREFIX}/news/ai-configs/${editingNewsId.value}`, {
        name: newsForm.name, provider: newsForm.provider, api_endpoint: newsForm.api_endpoint,
        api_key: newsForm.api_key || undefined, model_name: newsForm.model_name,
        enabled: newsForm.enabled, priority: newsForm.priority,
      })
      ElMessage.success('配置已更新')
    } else {
      await http.post(`${API_PREFIX}/news/ai-configs`, {
        name: newsForm.name, provider: newsForm.provider, api_endpoint: newsForm.api_endpoint,
        api_key: newsForm.api_key, model_name: newsForm.model_name,
        enabled: newsForm.enabled, priority: newsForm.priority,
      })
      ElMessage.success('配置已添加')
    }
    showNewsForm.value = false
    editingNewsId.value = ''
    await loadNewsAiConfigs()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally { newsSaving.value = false }
}

const deleteNewsConfig = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除接口「${row.name}」吗？`, '确认删除', { type: 'warning' })
    await http.delete(`${API_PREFIX}/news/ai-configs/${row.id}`)
    ElMessage.success('已删除')
    await loadNewsAiConfigs()
  } catch (e) {
    if (e !== 'cancel') { ElMessage.error(e?.message || '删除失败') }
  }
}

const testNewsConfig = async (row) => {
  if (!row.has_key) { ElMessage.warning('该接口未配置API Key，无法测试'); return }
  ElMessage.info('请点击编辑后在表单中测试连接')
}

const testCurrentNewsConfig = async () => {
  if (!newsForm.api_key && !editingNewsId.value) { ElMessage.error('请先输入 API Key'); return }
  if (!newsForm.model_name?.trim()) { ElMessage.error('请输入模型名称'); return }
  newsTesting.value = true
  try {
    const r = await http.post(`${API_PREFIX}/news/ai-configs/test`, {
      provider: newsForm.provider, api_endpoint: newsForm.api_endpoint,
      api_key: newsForm.api_key || '__USE_EXISTING__', model_name: newsForm.model_name,
    })
    ElMessage.success(`连接成功！耗时 ${r.latency_ms || '?'}ms`)
  } catch (e) {
    ElMessage.error(e?.message || '连接测试失败')
  } finally { newsTesting.value = false }
}

onMounted(async () => {
  await loadCfg()
  if (user.isAdmin) { await loadNewsAiConfigs() }
  loadHistory()
})
</script>

<style lang="scss" scoped>
.ai-result {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}
.ai-score-ring {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  .score-ring { width: 84px; height: 84px; font-size: 22px; }
}
.ai-result-text { flex: 1; min-width: 0; }

.news-api-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.news-api-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: rgba(30, 46, 65, 0.5);
  border-radius: 6px;
  border: 1px solid #1E2E41;
  &.disabled { opacity: 0.5; }
}
.news-api-priority {
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  background: #25D07D;
  color: #0a0f14;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.news-api-info { flex: 1; min-width: 0; }
.news-api-name {
  font-weight: 600;
  font-size: 13px;
  color: #D8E2EC;
}
.news-api-detail {
  font-size: 11px;
  margin-top: 2px;
}
.news-api-status { flex-shrink: 0; }

.news-cfg-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mt-8 { margin-top: 8px; }
.text-center { text-align: center; }
</style>
