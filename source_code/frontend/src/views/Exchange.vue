<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Wallet /></el-icon>交易所子账号管理</h2>
        <div class="page-subtitle">绑定币安 / OKX / Bybit 交易所子账号API，支持多账号隔离与余额同步</div>
      </div>
      <el-button type="primary" :icon="Plus" size="large" @click="openCreate">
        绑定新子账号
      </el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.exchange" placeholder="交易所" clearable style="width: 160px;">
        <el-option :value="1" label="币安 Binance" />
        <el-option :value="2" label="欧易 OKX" />
        <el-option :value="3" label="Bybit" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px;">
        <el-option :value="1" label="启用" />
        <el-option :value="0" label="禁用" />
        <el-option :value="2" label="API异常" />
      </el-select>
      <el-button :icon="RefreshRight" @click="loadList">刷新</el-button>
    </div>

    <!-- 账号卡片列表 -->
    <div v-loading="loading" style="min-height:200px;">
    <el-row :gutter="16">
      <el-col :span="12" v-for="a in list" :key="a.id">
        <div class="account-card" :class="'ex-' + a.exchange">
          <div class="flex-between mb-12">
            <div class="flex gap-12">
              <div class="ex-logo" :style="{ background: EXCHANGE_META[a.exchange]?.color }">
                {{ a.exchange === 1 ? 'BN' : 'OK' }}
              </div>
              <div>
                <div class="text-strong" style="font-size:16px;">{{ a.sub_account_name }}</div>
                <div class="text-dim" style="font-size:12px;display:flex;align-items:center;gap:4px;flex-wrap:wrap;">
                  <el-tag size="small" effect="dark">{{ EXCHANGE_META[a.exchange]?.name }}</el-tag>
                  <el-tag size="small" :type="a.testnet ? 'info' : 'warning'" effect="dark" style="margin-left:6px;">
                    {{ a.testnet ? '测试网' : '主网' }}
                  </el-tag>
                  <span style="display:flex;align-items:center;gap:4px;margin-left:6px;">
                    <span class="status-light" :class="a.status===1?'ok':(a.status===2?'error':'idle')"></span>
                    <el-tag size="small" :type="a.status===1?'success':(a.status===2?'danger':'info')" effect="dark">
                      {{ a.status===1 ? '启用' : a.status===2 ? 'API异常' : '禁用' }}
                    </el-tag>
                  </span>
                </div>
              </div>
            </div>
            <el-dropdown>
              <el-button :icon="MoreFilled" circle text />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="onEdit(a)"><el-icon><Edit /></el-icon>编辑配置</el-dropdown-item>
                  <el-dropdown-item @click="onSync(a)"><el-icon><Refresh /></el-icon>同步余额</el-dropdown-item>
                  <el-dropdown-item @click="onViewSecret(a)"><el-icon><Key /></el-icon>查看密钥</el-dropdown-item>
                  <el-dropdown-item divided @click="onDelete(a)" type="danger"><el-icon><Delete /></el-icon>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <el-row :gutter="12" style="margin-top: 8px;">
            <el-col :span="6">
              <div class="text-dim" style="font-size:11px;">当前权益</div>
              <div class="monospace text-strong" style="font-size:18px;">${{ fmtMoney(a.current_balance) }}</div>
            </el-col>
            <el-col :span="6">
              <div class="text-dim" style="font-size:11px;">可用余额</div>
              <div class="monospace" style="font-size:18px;">${{ fmtMoney(a.available_balance) }}</div>
            </el-col>
            <el-col :span="6">
              <div class="text-dim" style="font-size:11px;">未实现盈亏</div>
              <div class="monospace" :class="fmtPnlClass(a.unrealized_pnl)" style="font-size:18px;">
                {{ Number(a.unrealized_pnl) >= 0 ? '+' : '' }}${{ fmtMoney(a.unrealized_pnl) }}
              </div>
            </el-col>
            <el-col :span="6">
              <div class="text-dim" style="font-size:11px;">累计已实现</div>
              <div class="monospace" :class="fmtPnlClass(a.realized_pnl_total)" style="font-size:18px;">
                {{ Number(a.realized_pnl_total) >= 0 ? '+' : '' }}${{ fmtMoney(a.realized_pnl_total) }}
              </div>
            </el-col>
          </el-row>

          <div class="mt-16 flex-between">
            <div class="text-dim" style="font-size:12px;">
              允许杠杆上限: <b class="text-warn">{{ a.leverage_max }}x</b>
              <span style="margin-left:16px;">子账号ID: <span class="monospace">{{ a.sub_account_id || '-' }}</span></span>
            </div>
            <el-button size="small" :icon="Histogram" link type="primary" @click="goDetail(a)">查看报表</el-button>
          </div>
        </div>
      </el-col>
    </el-row>
    </div>

    <el-empty v-if="list.length === 0" description="暂无绑定的子账号，点击右上角绑定" />

    <!-- 子账号创建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑子账号配置' : '绑定新交易所子账号'" width="640px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:16px;"
        title="API Key 安全提醒">
        <template #default>
          <div>1. 建议为每个策略单独创建交易所子账号，设置 IP 白名单、开启只读/交易权限分离</div>
          <div>2. 生产环境请在 API 设置中<strong>禁用提币权限</strong></div>
        </template>
      </el-alert>
      <el-form label-width="130px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="交易所">
              <el-select v-model="accountForm.exchange" style="width:100%" :disabled="isEdit">
                <el-option label="币安 Binance" :value="1" />
                <el-option label="欧易 OKX" :value="2" />
                <el-option label="Bybit" :value="3" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="子账号名称">
              <el-input v-model="accountForm.sub_account_name" placeholder="如：主力策略_A 波段_账户1" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="子账号ID">
              <el-input v-model="accountForm.sub_account_id" placeholder="交易所后台分配的账户ID（可选）" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="允许最大杠杆">
              <el-input-number v-model="accountForm.leverage_max" :min="1" :max="10" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="isEdit ? '新 API Key' : 'API Key'">
              <el-input v-model="accountForm.api_key" type="password" show-password :placeholder="isEdit ? '留空则不修改原 Key' : '交易所生成的 API Key（≥8位）'" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="isEdit ? '新 API Secret' : 'API Secret'">
              <el-input v-model="accountForm.api_secret" type="password" show-password :placeholder="isEdit ? '留空则不修改原 Secret' : 'API Secret（≥8位）'" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Passphrase">
              <el-input v-model="accountForm.api_passphrase" type="password" show-password placeholder="OKX 需要，币安留空即可" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="IP 白名单">
              <el-input v-model="accountForm.ip_whitelist" placeholder="逗号分隔，如 1.2.3.4, 5.6.7.8" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="环境">
              <el-radio-group v-model="accountForm.testnet">
                <el-radio :value="true">测试网（Sandbox）</el-radio>
                <el-radio :value="false">主网（真实交易）</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-radio-group v-model="accountForm.status">
                <el-radio :value="1">启用</el-radio>
                <el-radio :value="0">禁用</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注"><el-input v-model="accountForm.remark" type="textarea" :rows="2" placeholder="策略用途说明、负责人等" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAccount">
          {{ isEdit ? '保存修改' : '确认绑定' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Wallet, Plus, RefreshRight, MoreFilled, Edit, Refresh, Key, Delete, Histogram,
} from '@element-plus/icons-vue'
import { EXCHANGE_META, fmtMoney, fmtPnlClass } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const router = useRouter()
const filters = reactive({ exchange: undefined, status: undefined })
const list = ref([])
const loading = ref(true)

// ========== 创建/编辑子账号对话框 ==========
const dialogVisible = ref(false)
const isEdit = ref(false)
const accountForm = reactive({
  id: null,
  exchange: 1,
  sub_account_name: '',
  sub_account_id: '',
  api_key: '',
  api_secret: '',
  api_passphrase: '',
  ip_whitelist: '',
  leverage_max: 5,
  testnet: true,
  status: 1,
  remark: '',
})
const resetForm = () => Object.assign(accountForm, {
  id: null, exchange: 1, sub_account_name: '', sub_account_id: '',
  api_key: '', api_secret: '', api_passphrase: '', ip_whitelist: '',
  leverage_max: 5, testnet: true, status: 1, remark: '',
})

const openCreate = () => { resetForm(); isEdit.value = false; dialogVisible.value = true }
const onEdit = (a) => {
  isEdit.value = true
  Object.assign(accountForm, {
    id: a.id,
    exchange: a.exchange,
    sub_account_name: a.sub_account_name || '',
    sub_account_id: a.sub_account_id || '',
    api_key: '',   // 编辑时不清空后端原密钥，留空代表"不改"
    api_secret: '',
    api_passphrase: '',
    ip_whitelist: a.ip_whitelist || '',
    leverage_max: a.leverage_max ?? 5,
    testnet: !!a.testnet,
    status: a.status ?? 1,
    remark: a.remark || '',
  })
  dialogVisible.value = true
}

const submitAccount = async () => {
  try {
    if (!accountForm.sub_account_name) return ElMessage.warning('请填写子账号名称')
    if (!isEdit.value) {
      if (!accountForm.api_key || !accountForm.api_secret) {
        return ElMessage.warning('请填写 API Key 与 Secret')
      }
      if (accountForm.api_key.length < 8 || accountForm.api_secret.length < 8) {
        return ElMessage.warning('API Key / Secret 长度不足')
      }
    }
    const payload = { ...accountForm }
    delete payload.id

    if (!isEdit.value) {
      await http.post(`${API_PREFIX}/exchange/accounts`, payload)
      ElMessage.success('子账号绑定成功')
    } else {
      // 编辑：空字符串字段（未填的 Key/Secret）不传，避免覆盖原值
      const updatePayload = {}
      Object.entries(payload).forEach(([k, v]) => {
        if (['api_key', 'api_secret', 'api_passphrase'].includes(k)) {
          if (v) updatePayload[k] = v
        } else {
          updatePayload[k] = v
        }
      })
      await http.put(`${API_PREFIX}/exchange/accounts/${accountForm.id}`, updatePayload)
      ElMessage.success('子账号配置已更新')
    }
    dialogVisible.value = false
    loadList()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  }
}

const loadList = async () => {
  loading.value = true
  try {
    const r = await http.get(`${API_PREFIX}/exchange/accounts`, { ...filters, page_size: 100 })
    list.value = r.items || []
  } catch (e) {
    console.warn('[Exchange] 加载失败:', e)
  } finally {
    loading.value = false
  }
}
const onSync = async (a) => {
  try {
    await http.post(`${API_PREFIX}/exchange/accounts/${a.id}/sync`)
    ElMessage.success('同步成功')
    loadList()
  } catch (e) {
    ElMessage.error(e?.message || '同步失败，请稍后重试')
  }
}
const onViewSecret = (a) => ElMessageBox.alert('（需二次验证后才展示）API Key: ********', '敏感信息', { type: 'warning' })
const onDelete = async (a) => {
  try {
    await ElMessageBox.confirm(`确定删除子账号 ${a.sub_account_name}？\n（有持仓时删除会被拒绝）`, '确认', { type: 'warning' })
    await http.delete(`${API_PREFIX}/exchange/accounts/${a.id}`)
    ElMessage.success('删除成功')
    loadList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}
const goDetail = (a) => router.push({ path: '/reports', query: { account_id: a.id } })

onMounted(loadList)
</script>

<style lang="scss" scoped>
.account-card {
  background: linear-gradient(145deg, #152330 0%, #121F2C 100%);
  border: 1px solid #1E2E41;
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 16px;
  transition: all .2s;
  &:hover {
    border-color: #29405A;
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(0,0,0,0.3);
  }
  &.ex-1 { border-left: 3px solid #F3BA2F; }
  &.ex-2 { border-left: 3px solid #97A6B6; }
}
.ex-logo {
  width: 46px; height: 46px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  color: #0F1A24; font-weight: 800; font-size: 16px;
  letter-spacing: -0.5px;
}
</style>
