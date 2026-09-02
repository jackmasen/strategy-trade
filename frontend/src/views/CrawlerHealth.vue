<template>
  <div class="page-container" v-loading="initialLoading" element-loading-text="加载中...">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Monitor /></el-icon> 爬虫健康监控</h2>
        <div class="page-subtitle">实时监控15个新闻爬虫的采集状态、代理池和Xray节点</div>
      </div>
    </div>

    <!-- 概览统计 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-card__label">爬虫总数</div>
          <div class="stat-card__value">{{ crawlerSummary?.total || 15 }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-ok">
          <div class="stat-card__label">正常</div>
          <div class="stat-card__value" style="color:#25D07D">{{ crawlerSummary?.healthy || 0 }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-warn">
          <div class="stat-card__label">异常</div>
          <div class="stat-card__value" style="color:#FBBF24">{{ crawlerSummary?.warning || 0 }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-err">
          <div class="stat-card__label">被屏蔽</div>
          <div class="stat-card__value" style="color:#F87171">{{ crawlerSummary?.critical || 0 }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 爬虫列表 -->
    <div class="panel-card mb-16">
      <div class="panel-card__header">
        <span class="panel-card__title">爬虫采集状态</span>
        <el-button type="primary" size="small" :loading="crawlerLoading" @click="loadCrawlerHealth(false)">刷新</el-button>
      </div>
      <div class="panel-card__body" style="padding: 0;">
        <el-table :data="crawlerList" stripe style="width: 100%" :row-class-name="crawlerRowClass">
          <el-table-column prop="source_name" label="数据源" width="140" />
          <el-table-column prop="crawler_class" label="爬虫类" width="180" />
          <el-table-column label="24h采集" width="100" align="center">
            <template #default="{ row }">
              <span :style="{ color: row.count_24h > 0 ? '#25D07D' : '#F87171', fontWeight: 'bold' }">{{ row.count_24h }}</span>
            </template>
          </el-table-column>
          <el-table-column label="7天采集" width="100" align="center">
            <template #default="{ row }">
              <span :style="{ color: row.count_7d > 0 ? '#25D07D' : '#F87171' }">{{ row.count_7d }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最后采集时间" width="160" align="center">
            <template #default="{ row }">{{ formatTime(row.last_article_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="120" align="center">
            <template #default="{ row }">
              <div class="status-badge" :class="row.status">
                <span class="status-dot" :class="row.status"></span>
                {{ row.status_cn }}
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- Xray节点管理 -->
    <div class="panel-card mb-16">
      <div class="panel-card__header">
        <span class="panel-card__title">Xray 节点管理（VLESS/VMess/Trojan/SS → 本地SOCKS5）</span>
        <div>
          <el-tag v-if="xrayInstalled" type="success" size="small" effect="dark">Xray已安装</el-tag>
          <el-tag v-else type="danger" size="small" effect="dark">Xray未安装</el-tag>
          <el-tag v-if="xrayRunning" type="success" size="small" effect="dark" style="margin-left:6px;">运行中</el-tag>
        </div>
      </div>
      <div class="panel-card__body">
        <!-- Xray未安装时显示安装提示 -->
        <el-alert v-if="!xrayInstalled"
          title="Xray未安装"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 16px;"
        >
          <template #default>
            Xray-core 是将 VLESS/VMess/Trojan 协议转换为本地 SOCKS5 代理的必要组件。点击下方按钮自动下载安装（约20MB）。
          </template>
        </el-alert>

        <el-form :inline="true" label-width="100px">
          <el-form-item label="订阅链接">
            <el-input v-model="xraySubUrl" placeholder="粘贴 vless:// vmess:// trojan:// ss:// 或订阅URL" style="width:500px;" />
          </el-form-item>
          <el-form-item>
            <el-button v-if="!xrayInstalled" type="warning" @click="installXray" :loading="installingXray" style="margin-right:8px;">
              {{ installingXray ? '安装中...' : '安装Xray' }}
            </el-button>
            <el-button type="primary" @click="loadXraySubscription" :loading="loadingXraySub">解析节点</el-button>
            <el-button type="success" @click="startXrayAll" :loading="startingXray" style="margin-left:8px;">启动全部</el-button>
            <el-button type="danger" @click="stopXrayAll" :loading="stoppingXray" style="margin-left:8px;">停止全部</el-button>
            <el-button type="warning" @click="checkXrayAll" :loading="checkingXray" style="margin-left:8px;">检测全部</el-button>
            <el-button @click="loadXrayStatus(false)" :loading="loadingXrayStatus" style="margin-left:8px;">刷新状态</el-button>
          </el-form-item>
        </el-form>

        <!-- 解析结果 -->
        <div v-if="xrayParseResult" style="margin-top:12px;">
          <el-alert
            :title="xrayParseResult.error ? `解析失败: ${xrayParseResult.error}` : `解析成功: ${xrayParseResult.parsed} 个节点`"
            :type="xrayParseResult.error ? 'error' : 'success'"
            :closable="false"
            show-icon
          />
        </div>

        <!-- 节点状态表格 -->
        <el-table v-if="xrayStatus?.nodes?.length" :data="xrayStatus.nodes" stripe style="width: 100%; margin-top: 12px;" max-height="300">
          <el-table-column label="节点名称" width="200">
            <template #default="{ row }">{{ row.name || row.tag || '—' }}</template>
          </el-table-column>
          <el-table-column label="协议" width="80">
            <template #default="{ row }">{{ row.protocol || '—' }}</template>
          </el-table-column>
          <el-table-column label="本地端口" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.local_port">:{{ row.local_port }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="延迟" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.latency_ms" :style="{color: row.latency_ms < 1000 ? '#25D07D' : row.latency_ms < 3000 ? '#FBBF24' : '#F87171'}">{{ row.latency_ms }}ms</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120" align="center">
            <template #default="{ row }">
              <div class="status-badge" :class="row.check_ok === true ? 'healthy' : row.check_ok === false ? 'critical' : 'warning'">
                <span class="status-dot" :class="row.check_ok === true ? 'healthy' : row.check_ok === false ? 'critical' : 'warning'"></span>
                {{ row.check_ok === true ? '正常' : row.check_ok === false ? '失败' : '未检测' }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="运行" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'running' ? 'success' : 'info'" size="small">{{ row.status === 'running' ? '运行中' : '已停止' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 代理配置 -->
    <div class="panel-card">
      <div class="panel-card__header">
        <span class="panel-card__title">代理配置</span>
        <el-button size="small" @click="loadProxyHealth(false)" :loading="loadingProxyHealth">刷新代理池</el-button>
      </div>
      <div class="panel-card__body">
        <el-form label-width="120px">
          <el-form-item label="启用代理">
            <el-switch v-model="proxy.enabled" />
          </el-form-item>
          <el-form-item label="订阅URL">
            <el-input v-model="proxy.provider_url" placeholder="代理订阅URL（支持Base64/Clash YAML/纯文本）" />
          </el-form-item>
          <el-form-item label="刷新间隔(分钟)">
            <el-input-number v-model="proxy.refresh_minutes" :min="5" :max="120" />
          </el-form-item>
          <el-form-item label="静态代理列表">
            <el-input v-model="proxy.http_list" type="textarea" :rows="3" placeholder="一行一个，支持 http://ip:port 或 socks5://ip:port" />
          </el-form-item>
          <el-form-item label="代理TTL(分钟)">
            <el-input-number v-model="proxy.ttl" :min="5" :max="1440" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveProxy" :loading="savingProxy">保存并热重载</el-button>
            <el-button type="warning" @click="refreshProxies" :loading="refreshingProxy" style="margin-left:10px;">立即拉取节点</el-button>
            <el-button type="success" @click="checkAllProxies" :loading="checkingProxies" style="margin-left:10px;">检测全部节点</el-button>
          </el-form-item>
        </el-form>

        <!-- 代理池状态 -->
        <div v-if="proxyPool" style="margin-top:16px;">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="代理总数">{{ proxyPool.total || 0 }}</el-descriptions-item>
            <el-descriptions-item label="可用">
              <span style="color:#25D07D;font-weight:bold;">{{ proxyPool.active || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="失效">
              <span style="color:#F87171;">{{ proxyPool.inactive || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="即将过期">{{ proxyPool.expiring || 0 }}</el-descriptions-item>
          </el-descriptions>

          <!-- 代理节点列表 -->
          <el-table v-if="proxyPool.all_proxies_detail?.length" :data="proxyPool.all_proxies_detail" stripe style="width: 100%; margin-top: 12px;" max-height="250">
            <el-table-column label="代理地址" prop="url" width="250" />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <div class="status-badge" :class="row.last_check_ok === true ? 'healthy' : row.last_check_ok === false ? 'critical' : 'warning'">
                  <span class="status-dot" :class="row.last_check_ok === true ? 'healthy' : row.last_check_ok === false ? 'critical' : 'warning'"></span>
                  {{ row.last_check_ok === true ? '正常' : row.last_check_ok === false ? '失败' : '未检测' }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="100" align="center">
              <template #default="{ row }">
                <span v-if="row.check_latency_ms" :style="{color: row.check_latency_ms < 1000 ? '#25D07D' : '#FBBF24'}">{{ row.check_latency_ms }}ms</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="使用次数" prop="use_count" width="100" align="center" />
            <el-table-column label="错误次数" width="100" align="center">
              <template #default="{ row }">
                <span :style="{color: row.fail_count > 0 ? '#F87171' : '#97A6B6'}">{{ row.fail_count || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最后检测" width="160" align="center">
              <template #default="{ row }">{{ formatTime(row.last_check_at) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import { http, API_PREFIX } from '@/utils/request'

const initialLoading = ref(true)

// 爬虫健康
const crawlerList = ref([])
const crawlerSummary = ref(null)
const crawlerLoading = ref(false)

const loadCrawlerHealth = async (silent = false) => {
  crawlerLoading.value = true
  try {
    const data = await http.get(`${API_PREFIX}/news/crawler-health`)
    crawlerList.value = data.crawlers || []
    crawlerSummary.value = data.summary || null
    if (!silent) ElMessage.success(`检测完成: ${data.summary.healthy}/${data.summary.total} 个爬虫正常`)
  } catch (e) {
    ElMessage.error('爬虫健康数据加载失败')
  } finally {
    crawlerLoading.value = false
  }
}

const formatTime = (iso) => {
  if (!iso) return '从未采集'
  try {
    const d = new Date(iso)
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    return `${mm}-${dd} ${hh}:${mi}`
  } catch {
    return iso
  }
}

const crawlerRowClass = ({ row }) => {
  return row.status === 'healthy' ? 'row-healthy' : row.status === 'warning' ? 'row-warning' : 'row-critical'
}

// 代理配置
const proxy = reactive({
  enabled: false,
  http_list: '',
  provider_url: '',
  refresh_minutes: 20,
  ttl: 25,
})
const savingProxy = ref(false)
const refreshingProxy = ref(false)
const proxyPool = ref(null)
const loadingProxyHealth = ref(false)

const loadProxyConfig = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/settings/proxy`)
    proxy.enabled = data.enabled || false
    proxy.http_list = data.http_list || ''
    proxy.provider_url = data.provider_url || ''
    proxy.refresh_minutes = data.refresh_minutes || 20
    proxy.ttl = data.ttl || 25
  } catch (e) {}
}

const loadProxyHealth = async (silent = false) => {
  loadingProxyHealth.value = true
  try {
    const data = await http.get(`${API_PREFIX}/settings/proxy/health`)
    proxyPool.value = data
    if (!silent) ElMessage.success(`代理池刷新完成: ${data.active || 0}/${data.total || 0} 个可用`)
  } catch (e) {
    if (!silent) ElMessage.error('代理状态刷新失败')
  } finally {
    loadingProxyHealth.value = false
  }
}

const saveProxy = async () => {
  savingProxy.value = true
  try {
    const data = await http.put(`${API_PREFIX}/settings/proxy`, {
      enabled: proxy.enabled,
      http_list: proxy.http_list,
      provider_url: proxy.provider_url,
      refresh_minutes: proxy.refresh_minutes,
      ttl: proxy.ttl,
    })
    ElMessage.success(data.message || '代理配置已保存')
    await loadProxyHealth(true)
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingProxy.value = false
  }
}

const refreshProxies = async () => {
  refreshingProxy.value = true
  try {
    const data = await http.post(`${API_PREFIX}/settings/proxy/refresh`)
    ElMessage.success(data.message || '刷新完成')
    await loadProxyHealth(true)
  } catch (e) {
    ElMessage.error(e?.message || '刷新失败')
  } finally {
    refreshingProxy.value = false
  }
}

const checkingProxies = ref(false)

const checkAllProxies = async () => {
  checkingProxies.value = true
  try {
    const data = await http.post(`${API_PREFIX}/settings/proxy/check-all`)
    ElMessage.success(`检测完成: ${data.ok}/${data.total} 个节点正常`)
    await loadProxyHealth(true)
  } catch (e) {
    ElMessage.error(e?.message || '检测失败')
  } finally {
    checkingProxies.value = false
  }
}

// Xray 节点管理
const xraySubUrl = ref('')
const xrayStatus = ref(null)
const xrayParseResult = ref(null)
const loadingXraySub = ref(false)
const startingXray = ref(false)
const stoppingXray = ref(false)
const checkingXray = ref(false)
const loadingXrayStatus = ref(false)
const installingXray = ref(false)

const xrayInstalled = ref(false)
const xrayRunning = ref(false)

const installXray = async () => {
  installingXray.value = true
  try {
    const data = await http.post(`${API_PREFIX}/settings/xray/install`)
    if (data.xray_available ?? data.installed) {
      ElMessage.success('Xray安装成功')
      xrayInstalled.value = true
      await loadXrayStatus(true)
    } else {
      ElMessage.error(`安装失败: ${data.error || '未知错误'}`)
    }
  } catch (e) {
    ElMessage.error('安装请求失败')
  } finally {
    installingXray.value = false
  }
}

const loadXraySubscription = async () => {
  if (!xraySubUrl.value) {
    ElMessage.warning('请先粘贴订阅链接或节点链接')
    return
  }
  loadingXraySub.value = true
  xrayParseResult.value = null
  try {
    const isLink = xraySubUrl.value.startsWith('vless://') || xraySubUrl.value.startsWith('vmess://') || xraySubUrl.value.startsWith('trojan://') || xraySubUrl.value.startsWith('ss://')
    const body = isLink ? { link: xraySubUrl.value } : { url: xraySubUrl.value }
    const data = await http.post(`${API_PREFIX}/settings/xray/load-subscription`, body)
    xrayParseResult.value = data
    if (data.error) {
      ElMessage.error(`解析失败: ${data.error}`)
    } else {
      ElMessage.success(`解析成功: ${data.parsed} 个节点`)
      await loadXrayStatus(true)
    }
  } catch (e) {
    xrayParseResult.value = { error: e?.message || '请求失败' }
    ElMessage.error('解析失败')
  } finally {
    loadingXraySub.value = false
  }
}

const loadXrayStatus = async (silent = false) => {
  loadingXrayStatus.value = true
  try {
    const data = await http.get(`${API_PREFIX}/settings/xray/status`)
    xrayStatus.value = data
    xrayInstalled.value = (data.xray_available ?? data.installed) || false
    xrayRunning.value = data.running || false
    const running = data.nodes?.filter(n => n.status === 'running').length || 0
    if (!silent) ElMessage.success(`Xray状态刷新完成: ${running}/${data.nodes?.length || 0} 个节点运行中`)
  } catch (e) {
    if (!silent) ElMessage.error('Xray状态刷新失败')
  } finally {
    loadingXrayStatus.value = false
  }
}

const startXrayAll = async () => {
  startingXray.value = true
  try {
    if (!xrayInstalled.value) {
      ElMessage.info('Xray未安装，正在自动下载安装...')
      const inst = await http.post(`${API_PREFIX}/settings/xray/install`)
      if (inst.xray_available ?? inst.installed) {
        xrayInstalled.value = true
        ElMessage.success('Xray安装成功，正在启动节点...')
      } else {
        ElMessage.error(`安装失败: ${inst.error || '未知错误'}`)
        startingXray.value = false
        return
      }
    }
    const data = await http.post(`${API_PREFIX}/settings/xray/start-all`)
    if (data.error) {
      ElMessage.error(data.error)
    } else {
      ElMessage.success(`启动成功: ${data.started}/${data.total} 个节点运行`)
      await loadXrayStatus(true)
    }
  } catch (e) {
    ElMessage.error(e?.message || '启动失败')
  } finally {
    startingXray.value = false
  }
}

const stopXrayAll = async () => {
  stoppingXray.value = true
  try {
    await http.post(`${API_PREFIX}/settings/xray/stop-all`)
    ElMessage.success('所有Xray节点已停止')
    await loadXrayStatus(true)
  } catch (e) {
    ElMessage.error('停止失败')
  } finally {
    stoppingXray.value = false
  }
}

const checkXrayAll = async () => {
  checkingXray.value = true
  try {
    const data = await http.post(`${API_PREFIX}/settings/xray/check-all`)
    if (data.error) {
      ElMessage.error(data.error)
    } else {
      ElMessage.success(`检测完成: ${data.ok}/${data.total} 个节点正常`)
      await loadXrayStatus(true)
    }
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    checkingXray.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    loadCrawlerHealth(true),
    loadProxyConfig(),
    loadProxyHealth(true),
    loadXrayStatus(true),
  ])
  initialLoading.value = false
})
</script>

<style lang="scss" scoped>
.stat-card {
  background: #152330;
  border: 1px solid #1E2E41;
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  &.stat-ok { border-color: #1A382A; }
  &.stat-warn { border-color: #3D3219; }
  &.stat-err { border-color: #3D1919; }
  &__label { font-size: 13px; color: #8FA3B8; margin-bottom: 8px; }
  &__value { font-size: 32px; font-weight: bold; color: #FFFFFF; }
}
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  &.healthy { color: #25D07D; }
  &.warning { color: #FBBF24; }
  &.critical { color: #F87171; }
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  &.healthy {
    background: #25D07D;
    box-shadow: 0 0 6px #25D07D;
    animation: blink 2s infinite;
  }
  &.warning {
    background: #FBBF24;
    box-shadow: 0 0 6px #FBBF24;
    animation: blink 1s infinite;
  }
  &.critical {
    background: #F87171;
    box-shadow: 0 0 6px #F87171;
    animation: pulse 0.8s infinite;
  }
}
.mb-16 { margin-bottom: 16px; }
:deep(.row-healthy) { background: rgba(37, 208, 125, 0.05) !important; }
:deep(.row-warning) { background: rgba(251, 191, 36, 0.05) !important; }
:deep(.row-critical) { background: rgba(248, 113, 113, 0.05) !important; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(1.3); } }
</style>
