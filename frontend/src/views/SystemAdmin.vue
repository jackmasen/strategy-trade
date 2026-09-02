<template>
  <div class="system-admin-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统管理</h2>
        <div class="page-subtitle">健康检测 · 缓存清理 · 备份恢复 · 版本更新</div>
      </div>
    </div>

    <!-- 系统概览 -->
    <div class="panel-card mb-16">
      <div class="panel-card__header">
        <span class="panel-card__title">系统概览</span>
      </div>
      <div class="panel-card__body sys-overview">
        <div class="ov-item">
          <div class="ov-label">版本</div>
          <div class="ov-value">{{ sysInfo.version }}</div>
        </div>
        <div class="ov-item">
          <div class="ov-label">Python</div>
          <div class="ov-value">{{ sysInfo.python_version }}</div>
        </div>
        <div class="ov-item">
          <div class="ov-label">数据库大小</div>
          <div class="ov-value">{{ sysInfo.database_size_mb }} MB</div>
        </div>
        <div class="ov-item">
          <div class="ov-label">用户数</div>
          <div class="ov-value">{{ sysInfo.user_count }}</div>
        </div>
        <div class="ov-item">
          <div class="ov-label">当前持仓</div>
          <div class="ov-value">{{ sysInfo.open_position_count }}</div>
        </div>
        <div class="ov-item">
          <div class="ov-label">备份数</div>
          <div class="ov-value">{{ sysInfo.backup_count }}</div>
        </div>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="sys-tabs">
      <!-- 健康检测 -->
      <el-tab-pane label="健康检测" name="health">
        <!-- 系统运行状态实时监控 -->
        <div class="sys-monitor-bar">
          <div class="smb-header">
            <div class="smb-title">
              <el-icon :size="18" style="color:#25D07D"><Monitor /></el-icon>
              <span>系统运行状态</span>
            </div>
            <div class="smb-refresh" @click="loadMonitorStatus" title="刷新">
              <el-icon :size="14" :class="{ 'rotating': monitorLoading }"><Refresh /></el-icon>
            </div>
          </div>
          <div class="smb-body">
            <div class="smb-metric">
              <div class="smb-m-label">CPU 使用率</div>
              <div class="smb-m-bar">
                <div class="smb-m-fill" :style="{ width: monitorStatus.resources.cpu_percent + '%', background: cpuColor }"></div>
              </div>
              <div class="smb-m-value" :style="{ color: cpuColor }">{{ monitorStatus.resources.cpu_percent }}%</div>
            </div>
            <div class="smb-metric">
              <div class="smb-m-label">内存使用率</div>
              <div class="smb-m-bar">
                <div class="smb-m-fill" :style="{ width: monitorStatus.resources.memory_percent + '%', background: memColor }"></div>
              </div>
              <div class="smb-m-value" :style="{ color: memColor }">{{ monitorStatus.resources.memory_percent }}%</div>
            </div>
            <div class="smb-metric">
              <div class="smb-m-label">磁盘使用率</div>
              <div class="smb-m-bar">
                <div class="smb-m-fill" :style="{ width: monitorStatus.resources.disk_percent + '%', background: diskColor }"></div>
              </div>
              <div class="smb-m-value" :style="{ color: diskColor }">{{ monitorStatus.resources.disk_percent }}%</div>
            </div>
            <div class="smb-divider"></div>
            <div class="smb-info-item">
              <span class="smb-info-label">运行时长</span>
              <span class="smb-info-value">{{ monitorStatus.uptime }}</span>
            </div>
            <div class="smb-info-item">
              <span class="smb-info-label">系统版本</span>
              <span class="smb-info-value monospace">{{ monitorStatus.version }}</span>
            </div>
            <div class="smb-info-item">
              <span class="smb-info-label">定时任务</span>
              <span class="smb-dot" :class="monitorStatus.scheduler.status === 'running' ? 'dot-ok' : 'dot-warn'"></span>
              <span class="smb-info-value">{{ monitorStatus.scheduler.status === 'running' ? '正常' : '异常' }}</span>
            </div>
            <div class="smb-info-item">
              <span class="smb-info-label">问题数</span>
              <el-tag size="small" effect="dark" :type="issueTagType" round>{{ monitorStatus.issue_count?.total || 0 }}</el-tag>
            </div>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">系统健康检测</span>
            <div>
              <el-button type="primary" plain :loading="checking" @click="doCheck(false)">
                <el-icon><Monitor /></el-icon> 立即检测
              </el-button>
              <el-button type="success" plain :loading="checking" @click="doCheck(true)" style="margin-left:8px">
                <el-icon><Tools /></el-icon> 检测并自动修复
              </el-button>
            </div>
          </div>
          <div class="panel-card__body" v-if="healthResult">
            <div class="health-overall" :class="'status-' + healthResult.overall_status">
              <el-icon :size="32">
                <CircleCheck v-if="healthResult.overall_status==='healthy'" />
                <Warning v-else-if="healthResult.overall_status==='warning'" />
                <CircleClose v-else />
              </el-icon>
              <div>
                <div class="health-title">
                  {{ statusMap[healthResult.overall_status] }}
                </div>
                <div class="health-time">检测时间：{{ healthResult.checked_at }}</div>
              </div>
            </div>
            <div class="check-list">
              <div v-for="c in healthResult.checks" :key="c.key" class="check-item">
                <div class="check-status" :class="'dot-' + c.status"></div>
                <div class="check-name">{{ c.name }}</div>
                <div class="check-detail">{{ c.detail }}</div>
              </div>
            </div>
            <div v-if="healthResult.fixed?.length" class="fixed-list">
              <div class="fixed-title">
                <el-icon><Select /></el-icon> 已自动修复
              </div>
              <el-tag v-for="f in healthResult.fixed" :key="f.key" type="success" effect="light" size="small">
                {{ f.name }}
              </el-tag>
            </div>
          </div>
          <div class="panel-card__body empty-hint" v-else>
            点击"立即检测"开始系统健康检测
          </div>
        </div>
      </el-tab-pane>

      <!-- 缓存清理 -->
      <el-tab-pane label="缓存清理" name="cache">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">缓存清理</span>
            <div>
              <el-button type="danger" plain :loading="cleaning" :disabled="!selectedKeys.length" @click="doClean">
                <el-icon><Delete /></el-icon> 清理选中 ({{ selectedKeys.length }})
              </el-button>
            </div>
          </div>
          <div class="panel-card__body">
            <div class="cache-total">
              可释放空间：<b>{{ cacheInfo.total_size_mb }} MB</b>
            </div>
            <div class="cache-list">
              <div v-for="item in cacheInfo.items" :key="item.key" class="cache-item"
                   :class="{ disabled: !item.exists }">
                <el-checkbox v-model="selectedKeys" :value="item.key" :disabled="!item.exists" />
                <div class="cache-info">
                  <div class="cache-name">{{ item.description }}</div>
                  <div class="cache-path text-dim">{{ item.path }}</div>
                </div>
                <div class="cache-size">
                  <template v-if="item.exists">{{ item.size_mb }} MB</template>
                  <template v-else class="text-dim">—</template>
                </div>
              </div>
            </div>
            <div v-if="cleanResult" class="clean-result">
              <el-alert type="success" :closable="false">
                清理完成，释放空间 <b>{{ cleanResult.freed_mb }} MB</b>，共 {{ cleanResult.cleared_count }} 项
              </el-alert>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 备份管理 -->
      <el-tab-pane label="备份管理" name="backup">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">系统备份</span>
            <el-button type="primary" plain :loading="backingUp" @click="openBackupDialog">
              <el-icon><FolderAdd /></el-icon> 新建备份
            </el-button>
          </div>
          <div class="panel-card__body">
            <el-table :data="backupList.items" stripe>
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="file_name" label="备份文件" min-width="260" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="backupTypeMap[row.backup_type]?.type || 'info'" effect="plain">
                    {{ backupTypeMap[row.backup_type]?.label || row.backup_type }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">{{ row.size_mb }} MB</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTypeMap[row.status]" effect="dark">
                    {{ statusLabelMap[row.status] }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="备注" min-width="140" show-overflow-tooltip />
              <el-table-column prop="created_at" label="创建时间" width="170" />
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="row.status===2" size="small" type="warning" link @click="doRestore(row)">
                    恢复
                  </el-button>
                  <el-button size="small" type="danger" link @click="doDeleteBackup(row)">
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="table-pager">
              <el-pagination v-model:current-page="backupPage" :page-size="20" :total="backupList.total"
                             layout="total, prev, pager, next" @current-change="loadBackups" />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 版本更新 -->
      <el-tab-pane label="版本更新" name="update">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">系统版本更新</span>
            <div class="flex gap-8">
              <el-button type="success" plain :loading="checkingGithub" @click="checkGithubUpdate">
                <el-icon><Download /></el-icon> 检查 GitHub 更新
              </el-button>
              <el-button type="primary" plain @click="openUploadDialog">
                <el-icon><Upload /></el-icon> 上传更新包
              </el-button>
            </div>
          </div>
          <div class="panel-card__body">
            <div class="update-tip">
              <el-icon><InfoFilled /></el-icon>
              <span>更新前系统会自动备份，更新失败可一键回滚到上一版本，数据安全有保障。</span>
            </div>

            <!-- GitHub 更新信息面板 -->
            <div v-if="githubInfo" class="github-update-panel">
              <div class="github-update-panel__header">
                <span class="github-update-panel__tag">
                  <el-tag size="small" type="success" effect="dark">{{ githubInfo.tag_name }}</el-tag>
                </span>
                <span class="github-update-panel__name">{{ githubInfo.name }}</span>
                <el-tag v-if="githubInfo.has_update" size="small" type="warning" effect="plain">有新版本</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">已是最新</el-tag>
              </div>
              <div class="github-update-panel__body">
                <div class="github-update-panel__row">
                  <span class="label">当前版本：</span>
                  <span>{{ githubInfo.current_version }}</span>
                </div>
                <div class="github-update-panel__row">
                  <span class="label">最新版本：</span>
                  <span>{{ githubInfo.tag_name }}</span>
                </div>
                <div v-if="githubInfo.body" class="github-update-panel__changelog">
                  <span class="label">更新日志：</span>
                  <pre>{{ githubInfo.body }}</pre>
                </div>
              </div>
              <div class="github-update-panel__footer">
                <el-button v-if="githubInfo.html_url" link type="primary" @click="openUrl(githubInfo.html_url)">
                  在 GitHub 查看
                </el-button>
                <el-button v-if="githubInfo.has_update" type="primary" :loading="githubUpdating" @click="doGithubUpdate">
                  下载并应用更新
                </el-button>
              </div>
            </div>

            <div class="update-history-title">更新历史</div>
            <el-table :data="updateList.items" stripe>
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="version" label="版本" width="120" />
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" type="info" effect="plain">{{ updateTypeMap[row.update_type] || row.update_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="source" label="来源" min-width="180" show-overflow-tooltip />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="updateStatusMap[row.status]?.type" effect="dark">
                    {{ updateStatusMap[row.status]?.label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="duration_sec" label="耗时(秒)" width="90" />
              <el-table-column prop="created_at" label="时间" width="170" />
              <el-table-column label="操作" width="140" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="row.status===2 && row.backup_id" size="small" type="warning" link @click="doRollback(row)">
                    回滚
                  </el-button>
                  <el-button v-if="row.error_msg" size="small" type="danger" link @click="showError(row)">
                    查看错误
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="table-pager">
              <el-pagination v-model:current-page="updatePage" :page-size="20" :total="updateList.total"
                             layout="total, prev, pager, next" @current-change="loadUpdates" />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 分享诊断 -->
      <el-tab-pane label="分享诊断" name="share">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">分享诊断链接</span>
            <el-button type="primary" :icon="Link" @click="showShareDialog = true">
              创建分享链接
            </el-button>
          </div>
          <div class="panel-card__body">
            <div class="share-tip">
              <el-alert type="info" :closable="false" show-icon>
                <template #title>安全说明</template>
                生成的分享链接可在有效期内让外部人员查看系统运行状态、日志和自检结果，用于远程诊断问题。
                分享数据已脱敏，不包含用户账号、API密钥等敏感信息。过期后链接自动失效。
              </el-alert>
            </div>

            <div class="share-stats">
              <div class="share-stat-item">
                <div class="ss-icon">🔗</div>
                <div class="ss-info">
                  <div class="ss-value">{{ shareTokens.length }}</div>
                  <div class="ss-label">有效链接</div>
                </div>
              </div>
              <div class="share-stat-item">
                <div class="ss-icon">⏱️</div>
                <div class="ss-info">
                  <div class="ss-value">30分钟</div>
                  <div class="ss-label">默认有效期</div>
                </div>
              </div>
              <div class="share-stat-item">
                <div class="ss-icon">🔒</div>
                <div class="ss-info">
                  <div class="ss-value">已脱敏</div>
                  <div class="ss-label">数据安全</div>
                </div>
              </div>
            </div>

            <el-table :data="shareTokens" stripe style="margin-top: 16px;">
              <el-table-column prop="token" label="分享令牌" width="260">
                <template #default="{ row }">
                  <span class="monospace" style="color:#94A3B8;">{{ row.token.slice(0, 16) }}...{{ row.token.slice(-8) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="访问次数" width="100" align="center">
                <template #default="{ row }">{{ row.access_count || 0 }}</template>
              </el-table-column>
              <el-table-column label="有效期" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" type="info">{{ row.ttl_hours }}小时</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="170">
                <template #default="{ row }">{{ row.created_at }}</template>
              </el-table-column>
              <el-table-column label="过期时间" width="170">
                <template #default="{ row }">
                  <span :class="isExpired(row) ? 'text-danger' : 'text-success'">{{ row.expires_at }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="dark" :type="isExpired(row) ? 'info' : 'success'">
                    {{ isExpired(row) ? '已过期' : '有效' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="copyShareUrl(row)">
                    复制链接
                  </el-button>
                  <el-button size="small" type="primary" link @click="openShareUrl(row)" v-if="!isExpired(row)">
                    打开
                  </el-button>
                  <el-button size="small" type="danger" link @click="revokeShare(row)" v-if="!isExpired(row)">
                    撤销
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="shareTokens.length === 0" class="share-empty">
              <el-empty description="暂无分享链接" :image-size="80" />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 创建分享链接对话框 -->
    <el-dialog v-model="showShareDialog" title="创建诊断分享链接" width="480px">
      <div class="share-create-form">
        <div class="form-item">
          <label>有效期</label>
          <el-select v-model="newShareTtl" style="width:100%;">
            <el-option label="30分钟（默认）" :value="0.5" />
            <el-option label="1小时" :value="1" />
            <el-option label="3小时" :value="3" />
            <el-option label="6小时" :value="6" />
            <el-option label="12小时" :value="12" />
            <el-option label="24小时" :value="24" />
            <el-option label="7天" :value="168" />
          </el-select>
          <div class="form-tip">
            <el-icon style="color:#f59e0b;"><Warning /></el-icon>
            链接过期后自动失效，建议根据实际需要选择最短的有效期
          </div>
        </div>
        <div class="form-item">
          <label>分享内容</label>
          <div class="share-content-list">
            <div class="share-content-item">
              <el-icon color="#25D07D"><CircleCheck /></el-icon>
              <span>系统运行状态（CPU/内存/磁盘/服务状态）</span>
            </div>
            <div class="share-content-item">
              <el-icon color="#25D07D"><CircleCheck /></el-icon>
              <span>功能自检结果（15项检测）</span>
            </div>
            <div class="share-content-item">
              <el-icon color="#25D07D"><CircleCheck /></el-icon>
              <span>运行日志（app/error，已脱敏）</span>
            </div>
            <div class="share-content-item">
              <el-icon color="#25D07D"><CircleCheck /></el-icon>
              <span>智能分析报告</span>
            </div>
            <div class="share-content-item share-content-disabled">
              <el-icon color="#64748B"><CircleClose /></el-icon>
              <span>用户数据、API密钥、交易密码等敏感信息</span>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showShareDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingShare" @click="createShare">
          创建并复制链接
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建备份对话框 -->
    <el-dialog v-model="backupDialogVisible" title="新建备份" width="460px">
      <el-form :model="backupForm" label-width="100px">
        <el-form-item label="包含数据库">
          <el-switch v-model="backupForm.include_db" />
        </el-form-item>
        <el-form-item label="包含配置">
          <el-switch v-model="backupForm.include_config" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="backupForm.description" placeholder="可选，如：更新前备份" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="backupDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="backingUp" @click="doCreateBackup">开始备份</el-button>
      </template>
    </el-dialog>

    <!-- 上传更新对话框 -->
    <el-dialog v-model="uploadDialogVisible" title="上传更新包" width="480px">
      <el-upload
        drag
        :auto-upload="false"
        :on-change="onFileChange"
        :limit="1"
        accept=".zip"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将 .zip 更新包拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 backend/ 或 frontend_dist/ 目录结构的 zip 包，最大 200MB
          </div>
        </template>
      </el-upload>
      <el-form :model="uploadForm" label-width="80px" style="margin-top:16px">
        <el-form-item label="版本号">
          <el-input v-model="uploadForm.version" placeholder="如 v1.1.0" />
        </el-form-item>
        <el-form-item label="更新说明">
          <el-input v-model="uploadForm.changelog" type="textarea" :rows="3" placeholder="描述本次更新内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadFile" @click="doUploadUpdate">
          上传并更新
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Monitor, Tools, Delete, FolderAdd, Upload, InfoFilled, UploadFilled,
  CircleCheck, Warning, CircleClose, Select, Download, Refresh, Link
} from '@element-plus/icons-vue'
import { http, API_PREFIX } from '@/utils/request'

const activeTab = ref('health')
const sysInfo = ref({})
const checking = ref(false)
const healthResult = ref(null)

const statusMap = {
  healthy: '系统运行健康',
  warning: '存在警告项',
  critical: '存在严重问题'
}

// -------- 系统运行状态监控 --------
const monitorLoading = ref(false)
const monitorStatus = ref({
  overall: 'healthy',
  version: 'v1.2.0',
  uptime: '—',
  resources: { cpu_percent: 0, memory_percent: 0, disk_percent: 0 },
  issue_count: { total: 0, critical: 0, warning: 0, info: 0 },
  scheduler: { status: 'unknown' },
  logs: {},
})

const cpuColor = computed(() => {
  const v = monitorStatus.value.resources.cpu_percent
  return v >= 80 ? '#f56c6c' : v >= 60 ? '#e6a23c' : '#25D07D'
})
const memColor = computed(() => {
  const v = monitorStatus.value.resources.memory_percent
  return v >= 85 ? '#f56c6c' : v >= 70 ? '#e6a23c' : '#25D07D'
})
const diskColor = computed(() => {
  const v = monitorStatus.value.resources.disk_percent
  return v >= 90 ? '#f56c6c' : v >= 75 ? '#e6a23c' : '#25D07D'
})
const issueTagType = computed(() => {
  const c = monitorStatus.value.issue_count
  if (c?.critical > 0) return 'danger'
  if (c?.warning > 0) return 'warning'
  return 'info'
})

function formatUptime(seconds) {
  if (!seconds) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return d + '天' + h + '时'
  if (h > 0) return h + '时' + m + '分'
  return m + '分钟'
}

let _monitorTimer = null
const loadMonitorStatus = async () => {
  monitorLoading.value = true
  try {
    const r = await http.get(API_PREFIX + '/monitor/status')
    if (r) {
      monitorStatus.value.overall = r.overall || 'healthy'
      monitorStatus.value.version = r.version || '—'
      monitorStatus.value.uptime = formatUptime(r.uptime_seconds)
      monitorStatus.value.resources = {
        cpu_percent: Math.round(r.resources?.cpu_percent || 0),
        memory_percent: Math.round(r.resources?.memory_percent || 0),
        disk_percent: Math.round(r.resources?.disk_percent || 0),
      }
      monitorStatus.value.issue_count = r.issue_count || { total: 0, critical: 0, warning: 0, info: 0 }
      monitorStatus.value.scheduler = r.scheduler || { status: 'unknown' }
      monitorStatus.value.logs = r.logs || {}
    }
  } catch (e) {
    // 静默失败
  } finally {
    monitorLoading.value = false
  }
}

// 缓存清理
const cacheInfo = ref({ items: [], total_size_mb: 0 })
const selectedKeys = ref([])
const cleaning = ref(false)
const cleanResult = ref(null)

// 备份
const backupDialogVisible = ref(false)
const backupForm = reactive({ include_db: true, include_config: true, description: '' })
const backupList = ref({ items: [], total: 0 })
const backupPage = ref(1)
const backingUp = ref(false)

const backupTypeMap = {
  manual: { label: '手动', type: 'primary' },
  auto: { label: '自动', type: 'success' },
  pre_update: { label: '更新前', type: 'warning' },
}
const statusLabelMap = { 1: '进行中', 2: '成功', 3: '失败' }
const statusTypeMap = { 1: 'info', 2: 'success', 3: 'danger' }

// 更新
const uploadDialogVisible = ref(false)
const uploadForm = reactive({ version: '', changelog: '' })
const uploadFile = ref(null)
const uploading = ref(false)
const updateList = ref({ items: [], total: 0 })
const updatePage = ref(1)
const checkingGithub = ref(false)
const githubInfo = ref(null)
const githubUpdating = ref(false)

const updateTypeMap = { upload: '上传', github: 'GitHub', rollback: '回滚' }
const updateStatusMap = {
  1: { label: '进行中', type: 'info' },
  2: { label: '成功', type: 'success' },
  3: { label: '失败', type: 'danger' },
  4: { label: '已回滚', type: 'warning' },
}

// ========== 系统信息 ==========
const loadSysInfo = async () => {
  try {
    sysInfo.value = await http.get(`${API_PREFIX}/system/info`)
  } catch (e) {}
}

// ========== 健康检测 ==========
const doCheck = async (autoFix) => {
  checking.value = true
  try {
    healthResult.value = await http.post(`${API_PREFIX}/system/health-check`, null, {
      params: { auto_fix: autoFix }
    })
    ElMessage.success(autoFix ? '检测并修复完成' : '检测完成')
    loadSysInfo()
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    checking.value = false
  }
}

// ========== 缓存清理 ==========
const loadCacheInfo = async () => {
  try {
    cacheInfo.value = await http.get(`${API_PREFIX}/system/cache/items`)
    // 默认选中所有存在的
    selectedKeys.value = cacheInfo.value.items.filter(i => i.exists).map(i => i.key)
  } catch (e) {}
}

const doClean = async () => {
  if (!selectedKeys.value.length) return
  try {
    await ElMessageBox.confirm(`确定清理选中的 ${selectedKeys.value.length} 项缓存？`, '确认清理', { type: 'warning' })
  } catch { return }

  cleaning.value = true
  try {
    cleanResult.value = await http.post(`${API_PREFIX}/system/cache/clean`, { keys: selectedKeys.value })
    ElMessage.success(`清理完成，释放 ${cleanResult.value.freed_mb} MB`)
    loadCacheInfo()
    loadSysInfo()
  } catch (e) {
    ElMessage.error('清理失败')
  } finally {
    cleaning.value = false
  }
}

// ========== 备份管理 ==========
const openBackupDialog = () => {
  backupForm.description = ''
  backupForm.include_db = true
  backupForm.include_config = true
  backupDialogVisible.value = true
}

const doCreateBackup = async () => {
  backingUp.value = true
  try {
    await http.post(`${API_PREFIX}/system/backups`, backupForm)
    ElMessage.success('备份创建成功')
    backupDialogVisible.value = false
    loadBackups()
    loadSysInfo()
  } catch (e) {
    ElMessage.error('备份失败')
  } finally {
    backingUp.value = false
  }
}

const loadBackups = async () => {
  try {
    backupList.value = await http.get(`${API_PREFIX}/system/backups`, {
      page: backupPage.value, page_size: 20
    })
  } catch (e) {}
}

const doRestore = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定从备份 "${row.file_name}" 恢复？\n将覆盖当前数据库和配置，建议先手动备份当前状态。`,
      '确认恢复',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
  } catch { return }

  try {
    const res = await http.post(`${API_PREFIX}/system/backups/${row.id}/restore`)
    ElMessage.success(res.message || '恢复成功')
    if (res.needs_restart) {
      ElMessageBox.alert('恢复完成，系统将在 3 秒后刷新...', '提示', { type: 'success' })
        .then(() => setTimeout(() => location.reload(), 3000))
    }
  } catch (e) {
    ElMessage.error('恢复失败')
  }
}

const doDeleteBackup = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除备份 "${row.file_name}"？`, '确认删除', { type: 'warning' })
  } catch { return }

  try {
    await http.delete(`${API_PREFIX}/system/backups/${row.id}`)
    ElMessage.success('删除成功')
    loadBackups()
    loadSysInfo()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// ========== 版本更新 ==========
const openUploadDialog = () => {
  uploadForm.version = ''
  uploadForm.changelog = ''
  uploadFile.value = null
  uploadDialogVisible.value = true
}

const onFileChange = (file) => {
  uploadFile.value = file.raw
}

const doUploadUpdate = async () => {
  if (!uploadFile.value) return
  uploading.value = true

  const fd = new FormData()
  fd.append('file', uploadFile.value)
  fd.append('version', uploadForm.version)
  fd.append('changelog', uploadForm.changelog)

  try {
    const res = await http.post(`${API_PREFIX}/system/updates/upload`, fd)
    ElMessage.success(res.message || '更新成功')
    uploadDialogVisible.value = false
    loadUpdates()
    if (res.needs_restart) {
      ElMessageBox.alert('更新完成，系统将在 3 秒后刷新...', '更新成功', { type: 'success' })
        .then(() => setTimeout(() => location.reload(), 3000))
    }
  } catch (e) {
    ElMessage.error(e?.message || '更新失败')
  } finally {
    uploading.value = false
  }
}

const loadUpdates = async () => {
  try {
    updateList.value = await http.get(`${API_PREFIX}/system/updates`, {
      page: updatePage.value, page_size: 20
    })
  } catch (e) {}
}

const doRollback = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定回滚到更新前的备份版本？\n当前更新版本：${row.version}`,
      '确认回滚',
      { type: 'warning' }
    )
  } catch { return }

  try {
    const res = await http.post(`${API_PREFIX}/system/updates/${row.id}/rollback`)
    ElMessage.success('回滚成功')
    loadUpdates()
    if (res.needs_restart) {
      ElMessageBox.alert('回滚完成，系统将在 3 秒后刷新...', '提示', { type: 'success' })
        .then(() => setTimeout(() => location.reload(), 3000))
    }
  } catch (e) {
    ElMessage.error('回滚失败')
  }
}

const showError = (row) => {
  ElMessageBox.alert(row.error_msg, '错误详情', { type: 'error', confirmButtonText: '知道了' })
}

// GitHub 更新
const checkGithubUpdate = async () => {
  checkingGithub.value = true
  try {
    const r = await http.get(`${API_PREFIX}/system/updates/check-latest`)
    githubInfo.value = r
    if (r.has_update) {
      ElMessage.success(`发现新版本: ${r.tag_name}`)
    } else {
      ElMessage.info(`当前已是最新版本: ${r.tag_name}`)
    }
  } catch (e) {
    // 拦截器已显示错误
  } finally {
    checkingGithub.value = false
  }
}

const doGithubUpdate = async () => {
  try {
    await ElMessageBox.confirm(
      `确定从 GitHub 下载并应用更新 ${githubInfo.value.tag_name}？\n\n更新前会自动备份，失败可回滚。`,
      '确认更新',
      { type: 'warning' }
    )
  } catch { return }

  githubUpdating.value = true
  try {
    const res = await http.post(`${API_PREFIX}/system/updates/github`, {}, { timeout: 180000 })
    ElMessage.success('GitHub 更新完成')
    githubInfo.value = null
    loadUpdates()
    if (res.needs_restart) {
      ElMessageBox.alert('更新完成，系统将在 3 秒后刷新...', '提示', { type: 'success' })
        .then(() => setTimeout(() => location.reload(), 3000))
    }
  } catch (e) {
    // 拦截器已显示错误
  } finally {
    githubUpdating.value = false
  }
}

const openUrl = (url) => {
  window.open(url, '_blank')
}

onMounted(() => {
  loadSysInfo()
  loadCacheInfo()
  loadBackups()
  loadUpdates()
  loadMonitorStatus()
  loadShareTokens()
  // 每30秒自动刷新系统运行状态
  _monitorTimer = setInterval(loadMonitorStatus, 30000)
})

onBeforeUnmount(() => {
  if (_monitorTimer) {
    clearInterval(_monitorTimer)
    _monitorTimer = null
  }
})

// ---------- 分享诊断 ----------
const showShareDialog = ref(false)
const creatingShare = ref(false)
const newShareTtl = ref(0.5) // 默认30分钟
const shareTokens = ref([])

async function loadShareTokens() {
  try {
    const r = await http.get(`${API_PREFIX}/monitor/share/list`)
    shareTokens.value = r.tokens || r.data?.tokens || []
  } catch (e) {
    shareTokens.value = []
  }
}

function isExpired(row) {
  return new Date(row.expires_at) < new Date()
}

async function createShare() {
  creatingShare.value = true
  try {
    const r = await http.post(`${API_PREFIX}/monitor/share`, {
      ttl_hours: newShareTtl.value,
    })
    const url = window.location.origin + r.share_url
    // 复制到剪贴板（兼容非安全上下文）
    let copied = false
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url)
        copied = true
      } else {
        // fallback: 使用 textarea + execCommand
        const ta = document.createElement('textarea')
        ta.value = url
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        document.body.appendChild(ta)
        ta.select()
        copied = document.execCommand('copy')
        document.body.removeChild(ta)
      }
    } catch (e) {
      copied = false
    }
    ElMessage.success(copied ? '分享链接已创建并复制到剪贴板' : '分享链接已创建')
    showShareDialog.value = false
    newShareTtl.value = 0.5
    loadShareTokens()
  } catch (e) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    creatingShare.value = false
  }
}

async function copyShareUrl(row) {
  const url = window.location.origin + '/monitor/share/' + row.token
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(url)
    } else {
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('链接已复制')
  } catch (e) {
    ElMessage.error('复制失败，请手动复制')
  }
}

function openShareUrl(row) {
  const url = '/monitor/share/' + row.token
  window.open(url, '_blank')
}

async function revokeShare(row) {
  try {
    await ElMessageBox.confirm(
      `确定撤销该分享链接？撤销后链接将立即失效。`,
      '确认撤销',
      { type: 'warning' }
    )
    await http.delete(`${API_PREFIX}/monitor/share/${row.token}`)
    ElMessage.success('已撤销')
    loadShareTokens()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('撤销失败')
    }
  }
}
</script>

<style lang="scss" scoped>
.system-admin-page {
  padding: 20px 24px 24px;
}
.sys-overview {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
  .ov-item {
    padding: 12px 16px;
    background: rgba(15, 26, 36, 0.6);
    border: 1px solid #1E2E41;
    border-radius: 10px;
    .ov-label { font-size: 12px; color: #6B7C90; margin-bottom: 6px; }
    .ov-value { font-size: 18px; font-weight: 600; color: #E2E8F0; }
  }
}
.sys-tabs {
  margin-top: 4px;
}

/* -------- 系统运行状态监控条 -------- */
.sys-monitor-bar {
  background: linear-gradient(135deg, #0F1A24 0%, #16232E 100%);
  border: 1px solid #1E3246;
  border-radius: 12px;
  margin-bottom: 16px;
  overflow: hidden;

  .smb-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 18px;
    border-bottom: 1px solid #1A2A3A;
    background: rgba(0,0,0,0.2);

    .smb-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 600;
      color: #E6EDF3;
    }
    .smb-refresh {
      cursor: pointer;
      color: #7A8A9A;
      padding: 4px;
      border-radius: 4px;
      transition: all 0.2s;
      &:hover { color: #25D07D; background: rgba(37,208,125,0.1); }
      .rotating {
        animation: spin 1s linear infinite;
        display: inline-block;
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }
    }
  }

  .smb-body {
    display: flex;
    align-items: center;
    padding: 14px 18px;
    gap: 20px;
    flex-wrap: wrap;
  }

  .smb-metric {
    flex: 1;
    min-width: 140px;
    display: flex;
    align-items: center;
    gap: 10px;

    .smb-m-label {
      font-size: 12px;
      color: #7A8A9A;
      min-width: 60px;
      font-weight: 500;
    }
    .smb-m-bar {
      flex: 1;
      height: 8px;
      background: #0A131B;
      border-radius: 4px;
      overflow: hidden;
      border: 1px solid #1A2A3A;

      .smb-m-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.5s ease, background 0.3s ease;
      }
    }
    .smb-m-value {
      font-size: 13px;
      font-weight: 600;
      min-width: 40px;
      text-align: right;
      font-family: Consolas, monospace;
    }
  }

  .smb-divider {
    width: 1px;
    height: 28px;
    background: #1A2A3A;
    margin: 0 4px;
  }

  .smb-info-item {
    display: flex;
    align-items: center;
    gap: 8px;

    .smb-info-label {
      font-size: 12px;
      color: #7A8A9A;
    }
    .smb-info-value {
      font-size: 13px;
      font-weight: 500;
      color: #E6EDF3;
    }
    .smb-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
      &.dot-ok { background: #25D07D; box-shadow: 0 0 6px rgba(37,208,125,0.5); }
      &.dot-warn { background: #e6a23c; box-shadow: 0 0 6px rgba(230,162,60,0.5); }
      &.dot-fail { background: #f56c6c; box-shadow: 0 0 6px rgba(245,108,108,0.5); }
    }
  }
}

/* 健康检测 */
.health-overall {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  &.status-healthy { background: rgba(37, 208, 125, 0.08); border: 1px solid rgba(37, 208, 125, 0.2); color: #25D07D; }
  &.status-warning { background: rgba(251, 191, 36, 0.08); border: 1px solid rgba(251, 191, 36, 0.2); color: #FBBF24; }
  &.status-critical { background: rgba(248, 113, 113, 0.08); border: 1px solid rgba(248, 113, 113, 0.2); color: #F87171; }
  .health-title { font-size: 18px; font-weight: 600; }
  .health-time { font-size: 12px; opacity: .7; margin-top: 2px; }
}
.check-list {
  display: flex; flex-direction: column; gap: 2px;
}
.check-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  &:hover { background: rgba(15, 26, 36, 0.5); }
}
.check-status {
  width: 10px; height: 10px; border-radius: 50%;
  &.dot-healthy { background: #25D07D; }
  &.dot-warning { background: #FBBF24; }
  &.dot-critical { background: #F87171; }
}
.check-name { width: 120px; font-size: 14px; color: #E2E8F0; }
.check-detail { flex: 1; font-size: 13px; color: #94A3B8; }
.fixed-list {
  margin-top: 14px; padding: 12px;
  background: rgba(37, 208, 125, 0.06);
  border: 1px solid rgba(37, 208, 125, 0.15);
  border-radius: 8px;
  .fixed-title { font-size: 13px; color: #25D07D; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
  .el-tag { margin-right: 6px; }
}
.empty-hint {
  text-align: center; color: #6B7C90; padding: 40px 0; font-size: 13px;
}

/* 缓存清理 */
.cache-total {
  font-size: 14px; color: #94A3B8; margin-bottom: 12px;
  b { color: #FBBF24; font-size: 16px; }
}
.cache-list { display: flex; flex-direction: column; gap: 4px; }
.cache-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px;
  border: 1px solid #1E2E41;
  border-radius: 10px;
  transition: all .2s;
  &:hover { border-color: #2F4A66; }
  &.disabled { opacity: .5; }
}
.cache-info { flex: 1; }
.cache-name { font-size: 14px; color: #E2E8F0; }
.cache-path { font-size: 12px; margin-top: 2px; }
.cache-size { font-size: 14px; color: #FBBF24; font-weight: 500; min-width: 90px; text-align: right; }
.clean-result { margin-top: 16px; }

/* 表格 */
.table-pager {
  display: flex; justify-content: flex-end;
  margin-top: 16px;
}
.update-tip {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px;
  background: rgba(96, 165, 250, 0.06);
  border: 1px solid rgba(96, 165, 250, 0.15);
  border-radius: 10px;
  color: #60A5FA;
  font-size: 13px;
  margin-bottom: 16px;
}
.update-history-title {
  font-size: 14px; font-weight: 600; color: #E2E8F0; margin-bottom: 10px;
}

/* GitHub 更新面板 */
.github-update-panel {
  margin-bottom: 16px;
  padding: 16px 20px;
  background: rgba(15, 26, 36, 0.6);
  border: 1px solid #1E2E41;
  border-radius: 12px;
}
.github-update-panel__header {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 12px;
}
.github-update-panel__name {
  font-size: 15px; font-weight: 600; color: #E2E8F0;
  flex: 1;
}
.github-update-panel__body {
  padding: 8px 0;
}
.github-update-panel__row {
  display: flex; gap: 8px;
  padding: 4px 0;
  font-size: 13px; color: #94A3B8;
  .label { min-width: 80px; color: #6B7C90; }
  span:last-child { color: #E2E8F0; }
}
.github-update-panel__changelog {
  margin-top: 8px;
  pre {
    margin-top: 6px;
    padding: 10px 12px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 8px;
    font-size: 12px;
    color: #B0BEC5;
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 200px;
    overflow-y: auto;
  }
}
.github-update-panel__footer {
  display: flex; justify-content: flex-end; gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #1E2E41;
}

.flex { display: flex; }
.gap-8 { gap: 8px; }

/* ---------- 分享诊断 ---------- */
.share-tip { margin-bottom: 16px; }
.share-stats {
  display: flex;
  gap: 16px;
  margin-top: 16px;

  .share-stat-item {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 18px 20px;
    background: linear-gradient(135deg, rgba(37,208,125,0.08) 0%, rgba(59,130,246,0.08) 100%);
    border: 1px solid rgba(37,208,125,0.2);
    border-radius: 12px;

    .ss-icon { font-size: 32px; }
    .ss-info {
      .ss-value {
        font-size: 22px;
        font-weight: 700;
        color: #E6EDF3;
        line-height: 1.2;
      }
      .ss-label {
        font-size: 12px;
        color: #94A3B8;
        margin-top: 4px;
      }
    }
  }
}
.share-empty {
  padding: 30px 0;
  text-align: center;
}

.share-create-form {
  .form-item {
    margin-bottom: 20px;

    label {
      display: block;
      font-size: 13px;
      color: #CBD5E1;
      margin-bottom: 8px;
      font-weight: 500;
    }
    .form-tip {
      margin-top: 8px;
      font-size: 12px;
      color: #94A3B8;
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }
  .share-content-list {
    background: #0A131B;
    border-radius: 8px;
    padding: 12px;
    border: 1px solid #1A2A3A;

    .share-content-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 0;
      font-size: 13px;
      color: #CBD5E1;

      &.share-content-disabled {
        color: #64748B;
        text-decoration: line-through;
      }
    }
  }
}
</style>
