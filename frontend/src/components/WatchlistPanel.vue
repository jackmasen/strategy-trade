<template>
  <div class="watchlist-panel">
    <!-- 头部：标题 + 添加按钮 -->
    <div class="wl-header">
      <div class="wl-title-row">
        <span class="status-light ok" style="margin:0;width:5px;height:5px;"></span>
        <span class="wl-title">自选列表</span>
        <el-tag size="small" type="info" effect="dark" round>{{ watchlist.length }}个</el-tag>
      </div>
      <div class="wl-add-row">
        <el-select
          v-model="newSymbol"
          placeholder="添加自选"
          size="small"
          filterable
          class="wl-add-select"
          @keyup.enter="handleAdd"
        >
          <el-option
            v-for="sym in availableSymbols"
            :key="sym"
            :label="`${SYMBOL_META[sym]?.icon || ''} ${sym} ${SYMBOL_META[sym]?.name || ''}`"
            :value="sym"
          />
        </el-select>
        <el-button size="small" type="primary" :icon="Plus" @click="handleAdd" :disabled="!newSymbol">添加</el-button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="wl-body">
      <!-- 空状态 -->
      <div v-if="watchlist.length === 0" class="wl-empty">
        <div class="wl-empty-icon">⭐</div>
        <div class="wl-empty-text">暂无自选币种</div>
        <div class="wl-empty-tip">在上方搜索添加你关注的品种</div>
      </div>

      <!-- 列表项 -->
      <div v-else class="wl-list">
        <div
          v-for="(item, index) in watchlist"
          :key="item.id"
          class="wl-item"
          :class="{ active: item.symbol === currentSymbol }"
          @click="handleSelect(item.symbol)"
        >
          <!-- 拖拽手柄（仅排序模式显示） -->
          <div v-if="dragMode" class="wl-drag-col">
            <span class="wl-drag-handle" @click.stop>☰</span>
          </div>

          <!-- 品种图标 -->
          <div class="wl-icon-col">
            <span class="wl-icon" :style="{ color: SYMBOL_META[item.symbol]?.color || '#94A3B8' }">
              {{ SYMBOL_META[item.symbol]?.icon || item.symbol.charAt(0) }}
            </span>
          </div>

          <!-- 品种名称 -->
          <div class="wl-name-col">
            <div class="wl-symbol">{{ item.symbol }}</div>
            <div class="wl-name">{{ SYMBOL_META[item.symbol]?.name || item.symbol }}</div>
          </div>

          <!-- 价格 -->
          <div class="wl-price-col">
            <div class="wl-price" :class="getTicker(item.symbol)?.change_pct_24h >= 0 ? 'profit' : 'loss'">
              ${{ fmtMoney(getTicker(item.symbol)?.last_price) }}
            </div>
            <div class="wl-change" :class="getTicker(item.symbol)?.change_pct_24h >= 0 ? 'profit' : 'loss'">
              <span class="wl-change-arrow">{{ getTicker(item.symbol)?.change_pct_24h >= 0 ? '▲' : '▼' }}</span>
              {{ getTicker(item.symbol)?.change_pct_24h >= 0 ? '+' : '' }}{{ (getTicker(item.symbol)?.change_pct_24h || 0).toFixed(2) }}%
            </div>
          </div>

          <!-- 操作列 -->
          <div class="wl-action-col" @click.stop>
            <!-- 排序模式：上下移动 -->
            <template v-if="dragMode">
              <el-button
                size="small"
                text
                :icon="Top"
                :disabled="index === 0"
                @click="moveUp(index)"
                title="上移"
              />
              <el-button
                size="small"
                text
                :icon="Bottom"
                :disabled="index === watchlist.length - 1"
                @click="moveDown(index)"
                title="下移"
              />
            </template>
            <!-- 正常模式：删除按钮 -->
            <template v-else>
              <el-button
                size="small"
                text
                type="danger"
                :icon="Close"
                @click="handleDelete(item)"
                title="移除自选"
              />
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div v-if="watchlist.length > 0" class="wl-footer">
      <el-button size="small" text @click="toggleDragMode">
        <el-icon v-if="!dragMode"><Rank /></el-icon>
        {{ dragMode ? '完成排序' : '管理排序' }}
      </el-button>
      <span class="wl-refresh-tip" v-if="lastUpdate">
        更新于 {{ formatTime(lastUpdate) }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { Plus, Close, Top, Bottom, Rank } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { SYMBOL_META, fmtMoney } from '@/utils/env'
import { http, API_PREFIX } from '@/utils/request'

const props = defineProps({
  currentSymbol: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select-symbol'])

// 数据
const watchlist = ref([])
const tickers = ref({})
const newSymbol = ref('')
const dragMode = ref(false)
const lastUpdate = ref(0)
let refreshTimer = null

// 可添加的品种（排除已添加的）
const availableSymbols = computed(() => {
  const added = new Set(watchlist.value.map(i => i.symbol))
  return Object.keys(SYMBOL_META).filter(s => !added.has(s))
})

// 获取某个品种的 ticker
const getTicker = (symbol) => {
  return tickers.value[symbol] || { last_price: 0, change_pct_24h: 0 }
}

// 格式化时间
const formatTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// 加载自选币列表
const loadWatchlist = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/watchlist`)
    watchlist.value = data.items || []
  } catch (e) {
    console.error('[Watchlist] 加载自选列表失败:', e)
  }
}

// 加载 ticker 数据
const loadTickers = async () => {
  if (watchlist.value.length === 0) return
  const symbols = watchlist.value.map(i => i.symbol).join(',')
  try {
    const data = await http.get(`${API_PREFIX}/exchange/tickers`, { symbols }, { _silent: true })
    const items = data.items || []
    const map = {}
    for (const t of items) {
      map[t.symbol] = t
    }
    tickers.value = map
    lastUpdate.value = Date.now()
  } catch (e) {
    // 静默失败
  }
}

// 添加自选币
const handleAdd = async () => {
  if (!newSymbol.value) return
  try {
    await http.post(`${API_PREFIX}/watchlist`, { symbol: newSymbol.value })
    ElMessage.success(`已添加 ${newSymbol.value} 到自选`)
    newSymbol.value = ''
    await loadWatchlist()
    loadTickers()
  } catch (e) {
    // 错误已由拦截器提示
  }
}

// 删除自选币
const handleDelete = async (item) => {
  try {
    await ElMessageBox.confirm(
      `确定要将 ${item.symbol} 从自选列表中移除吗？`,
      '移除确认',
      {
        confirmButtonText: '移除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await http.delete(`${API_PREFIX}/watchlist/${item.id}`)
    ElMessage.success(`已移除 ${item.symbol}`)
    await loadWatchlist()
    loadTickers()
  } catch (e) {
    if (e === 'cancel') return
  }
}

// 点击品种切换
const handleSelect = (symbol) => {
  emit('select-symbol', symbol)
}

// 上移
const moveUp = async (index) => {
  if (index <= 0) return
  const items = [...watchlist.value]
  ;[items[index - 1], items[index]] = [items[index], items[index - 1]]
  watchlist.value = items
  await saveReorder()
}

// 下移
const moveDown = async (index) => {
  if (index >= watchlist.value.length - 1) return
  const items = [...watchlist.value]
  ;[items[index + 1], items[index]] = [items[index], items[index + 1]]
  watchlist.value = items
  await saveReorder()
}

// 保存重排序
const saveReorder = async () => {
  const items = watchlist.value.map((item, idx) => ({
    id: item.id,
    sort_order: idx,
  }))
  try {
    await http.post(`${API_PREFIX}/watchlist/reorder`, { items })
  } catch (e) {
    console.error('[Watchlist] 保存排序失败:', e)
    ElMessage.warning('排序保存失败')
    loadWatchlist() // 重新加载恢复正确顺序
  }
}

// 切换排序模式
const toggleDragMode = () => {
  dragMode.value = !dragMode.value
  if (!dragMode.value) {
    ElMessage.success('排序已保存')
  }
}

// 启动定时器
const startTimer = () => {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = setInterval(() => {
    loadTickers()
  }, 3000)
}

// 停止定时器
const stopTimer = () => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// 监听列表变化，更新 ticker 刷新
watch(watchlist, (newList) => {
  if (newList.length > 0) {
    loadTickers()
  } else {
    tickers.value = {}
  }
}, { deep: true })

onMounted(() => {
  loadWatchlist().then(() => {
    loadTickers()
    startTimer()
  })
})

onBeforeUnmount(() => {
  stopTimer()
})
</script>

<style scoped>
.watchlist-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(15, 23, 42, 0.6);
  border-radius: 8px;
  overflow: hidden;
}

.wl-header {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(30, 41, 59, 0.8);
  flex-shrink: 0;
}

.wl-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.wl-title {
  font-size: 13px;
  font-weight: 600;
  color: #E2E8F0;
}

.wl-add-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.wl-add-select {
  flex: 1;
  min-width: 0;
}

.wl-body {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
}

.wl-body::-webkit-scrollbar {
  width: 4px;
}

.wl-body::-webkit-scrollbar-track {
  background: transparent;
}

.wl-body::-webkit-scrollbar-thumb {
  background: rgba(100, 116, 139, 0.3);
  border-radius: 2px;
}

/* 空状态 */
.wl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px 20px;
  color: #64748B;
}

.wl-empty-icon {
  font-size: 28px;
  margin-bottom: 8px;
  opacity: 0.5;
}

.wl-empty-text {
  font-size: 13px;
  margin-bottom: 4px;
  color: #94A3B8;
}

.wl-empty-tip {
  font-size: 11px;
  color: #64748B;
}

/* 列表 */
.wl-list {
  padding: 4px 0;
}

.wl-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  gap: 8px;
  border-bottom: 1px solid rgba(30, 41, 59, 0.5);
}

.wl-item:hover {
  background: rgba(30, 41, 59, 0.6);
}

.wl-item.active {
  background: rgba(59, 130, 246, 0.1);
  border-left: 2px solid #3B82F6;
  padding-left: 10px;
}

.wl-drag-col {
  flex-shrink: 0;
  width: 16px;
  text-align: center;
}

.wl-drag-handle {
  color: #64748B;
  cursor: grab;
  font-size: 12px;
}

.wl-drag-handle:active {
  cursor: grabbing;
}

.wl-icon-col {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wl-icon {
  font-size: 16px;
  font-weight: 700;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(30, 41, 59, 0.8);
  border-radius: 6px;
}

.wl-name-col {
  flex: 1;
  min-width: 0;
}

.wl-symbol {
  font-size: 13px;
  font-weight: 600;
  color: #E2E8F0;
  line-height: 1.2;
}

.wl-name {
  font-size: 11px;
  color: #64748B;
  line-height: 1.2;
  margin-top: 2px;
}

.wl-price-col {
  text-align: right;
  flex-shrink: 0;
}

.wl-price {
  font-size: 13px;
  font-weight: 600;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  line-height: 1.2;
}

.wl-price.profit {
  color: #F87171;
}

.wl-price.loss {
  color: #4ADE80;
}

.wl-change {
  font-size: 11px;
  margin-top: 2px;
  line-height: 1.2;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

.wl-change.profit {
  color: #F87171;
}

.wl-change.loss {
  color: #4ADE80;
}

.wl-change-arrow {
  font-size: 9px;
  margin-right: 1px;
}

.wl-action-col {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.wl-item:hover .wl-action-col {
  opacity: 1;
}

.wl-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-top: 1px solid rgba(30, 41, 59, 0.8);
  flex-shrink: 0;
}

.wl-refresh-tip {
  font-size: 10px;
  color: #64748B;
}
</style>
