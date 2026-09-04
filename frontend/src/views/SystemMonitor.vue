<template>
  <div class="system-monitor-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统监控</h2>
        <div class="page-subtitle">实时状态 · 运行日志 · 功能自检 · 分享诊断</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" :icon="Refresh" :loading="refreshing" @click="refreshAll">刷新</el-button>
        <el-button type="success" :icon="Link" @click="showShareDialog = true">生成分享链接</el-button>
      </div>
    </div>

    <div class="overview-row">
      <div class="status-card" :class="'status-' + status.overall">
        <div class="status-indicator">
          <div class="pulse-ring"></div>
          <div class="status-icon">
            <el-icon :size="48">
              <CircleCheck v-if="status.overall === 'healthy'" />
              <Warning v-else-if="status.overall === 'warning'" />
              <CircleClose v-else />
            </el-icon>
          </div>
        </div>
        <div class="status-info">
          <div class="status-title">{{ statusText }}</div>
          <div class="status-desc">{{ statusDesc }}</div>
          <div class="status-meta">
            <span>v{{ status.version || '1.2.0' }}</span>
            <span>运行 {{ formatUptime(status.uptime_seconds) }}</span>
          </div>
        </div>
        <div class="status-issues" v-if="status.issues?.length">
          <el-tag type="danger" effect="dark" v-if="status.issue_count?.critical">{{ status.issue_count.critical }} 严重</el-tag>
          <el-tag type="warning" effect="dark" v-if="status.issue_count?.warning">{{ status.issue_count.warning }} 警告</el-tag>
        </div>
      </div>

      <div class="metric-card" v-if="status.resources">
        <div class="metric-item">
          <div class="metric-label">CPU 使用率</div>
          <div class="metric-value" :class="getResourceClass(status.resources.cpu_percent, 80, 95)">
            {{ status.resources.cpu_percent?.toFixed?.(1) || '--' }}%
          </div>
          <el-progress :percentage="status.resources.cpu_percent || 0" :stroke-width="6" :color="getProgressColor(status.resources.cpu_percent, 80, 95)" />
        </div>
      </div>

      <div class="metric-card" v-if="status.resources">
        <div class="metric-item">
          <div class="metric-label">内存使用率</div>
          <div class="metric-value" :class="getResourceClass(status.resources.memory_percent, 80, 95)">
            {{ status.resources.memory_percent?.toFixed?.(1) || '--' }}%
          </div>
          <el-progress :percentage="status.resources.memory_percent || 0" :stroke-width="6" :color="getProgressColor(status.resources.memory_percent, 80, 95)" />
          <div class="metric-sub">{{ status.resources.memory_used_mb }} / {{ status.resources.memory_total_mb }} MB</div>
        </div>
      </div>

      <div class="metric-card" v-if="status.resources">
        <div class="metric-item">
          <div class="metric-label">磁盘使用率</div>
          <div class="metric-value" :class="getResourceClass(status.resources.disk_percent, 80, 95)">
            {{ status.resources.disk_percent?.toFixed?.(1) || '--' }}%
          </div>
          <el-progress :percentage="status.resources.disk_percent || 0" :stroke-width="6" :color="getProgressColor(status.resources.disk_percent, 80, 95)" />
          <div class="metric-sub">{{ status.resources.disk_free_gb }} GB 可用 / {{ status.resources.disk_total_gb }} GB</div>
        </div>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="monitor-tabs">
      <el-tab-pane label="实时状态" name="status">
        <div class="two-col">
          <div class="panel-card">
            <div class="panel-card__header"><span class="panel-card__title">服务状态</span></div>
            <div class="panel-card__body">
              <div class="service-list">
                <div class="service-item">
                  <div class="svc-icon db-icon"><el-icon><Coin /></el-icon></div>
                  <div class="svc-info">
                    <div class="svc-name">数据库</div>
                    <div class="svc-desc">{{ status.database?.connection === 'ok' ? '连接正常' : (status.database?.error || '未知') }}</div>
                  </div>
                  <div class="svc-status" style="display:flex;align-items:center;gap:6px;">
                    <span class="status-light" :class="status.database?.connection === 'ok' ? 'ok' : 'error'"></span>
                    <el-tag :type="status.database?.connection === 'ok' ? 'success' : 'danger'" effect="dark" size="small">
                      {{ status.database?.connection === 'ok' ? '运行中' : '异常' }}
                    </el-tag>
                  </div>
                </div>
                <div class="service-item">
                  <div class="svc-icon redis-icon"><el-icon><Lightning /></el-icon></div>
                  <div class="svc-info">
                    <div class="svc-name">Redis</div>
                    <div class="svc-desc">{{ status.redis?.host }}:{{ status.redis?.port }}</div>
                  </div>
                  <div class="svc-status" style="display:flex;align-items:center;gap:6px;">
                    <span class="status-light" :class="status.redis?.status === 'ok' ? 'ok' : (status.redis?.status === 'unavailable' ? 'idle' : 'error')"></span>
                    <el-tag :type="status.redis?.status === 'ok' ? 'success' : (status.redis?.status === 'unavailable' ? 'info' : 'warning')" effect="dark" size="small">
                      {{ status.redis?.status === 'ok' ? '运行中' : (status.redis?.status === 'unavailable' ? '未启用' : '异常') }}
                    </el-tag>
                  </div>
                </div>
                <div class="service-item">
                  <div class="svc-icon sched-icon"><el-icon><Timer /></el-icon></div>
                  <div class="svc-info">
                    <div class="svc-name">定时任务</div>
                    <div class="svc-desc">{{ status.scheduler?.mode || '未知' }} 模式</div>
                  </div>
                  <div class="svc-status" style="display:flex;align-items:center;gap:6px;">
                    <span class="status-light" :class="status.scheduler?.enabled ? 'ok' : 'warn'"></span>
                    <el-tag :type="status.scheduler?.enabled ? 'success' : 'warning'" effect="dark" size="small">
                      {{ status.scheduler?.enabled ? '运行中' : '未启用' }}
                    </el-tag>
                  </div>
                </div>
              </div>
              <div class="task-list" v-if="status.scheduler?.tasks?.length">
                <div class="task-item" v-for="t in status.scheduler.tasks" :key="t.name">
                    <span class="status-light ok"></span>
                    <span class="task-name">{{ t.name }}</span>
                    <span class="task-interval">{{ t.interval }}</span>
                    <el-tag size="small" type="success" effect="dark">运行中</el-tag>
                </div>
              </div>
            </div>
          </div>

          <div class="panel-card">
            <div class="panel-card__header">
              <span class="panel-card__title">检测到的问题</span>
              <el-tag size="small" :type="status.issues?.length ? 'warning' : 'success'" effect="dark">{{ status.issues?.length || 0 }} 项</el-tag>
            </div>
            <div class="panel-card__body">
              <div v-if="!status.issues?.length" class="empty-hint">
                <el-icon :size="40" color="#25D07D"><CircleCheck /></el-icon>
                <div style="margin-top:12px;">系统运行正常，未检测到问题</div>
              </div>
              <div v-else class="issue-list">
                <div v-for="(issue, idx) in status.issues" :key="idx" class="issue-item" :class="'level-' + issue.level">
                  <el-icon class="issue-icon"><CircleClose v-if="issue.level === 'critical'" /><Warning v-else /></el-icon>
                  <div class="issue-msg">{{ issue.msg }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="panel-card mt-16">
          <div class="panel-card__header">
            <span class="panel-card__title">今日日志统计</span>
            <el-button text type="primary" @click="activeTab = 'logs'">查看日志 &rarr;</el-button>
          </div>
          <div class="panel-card__body">
            <div class="log-stats-row">
              <div class="log-stat-item info"><div class="ls-count">{{ status.logs?.level_counts?.INFO || 0 }}</div><div class="ls-label">INFO</div></div>
              <div class="log-stat-item warning"><div class="ls-count">{{ status.logs?.level_counts?.WARNING || 0 }}</div><div class="ls-label">WARNING</div></div>
              <div class="log-stat-item error"><div class="ls-count">{{ status.logs?.level_counts?.ERROR || 0 }}</div><div class="ls-label">ERROR</div></div>
              <div class="log-stat-item debug"><div class="ls-count">{{ status.logs?.level_counts?.DEBUG || 0 }}</div><div class="ls-label">DEBUG</div></div>
              <div class="log-stat-item total"><div class="ls-count">{{ status.logs?.total_log_files || 0 }}</div><div class="ls-label">日志文件</div></div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="功能自检" name="selfcheck">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">完整功能自检</span>
            <div><el-button type="primary" :icon="Monitor" :loading="checking" @click="runSelfCheck">运行自检</el-button></div>
          </div>
          <div class="panel-card__body" v-if="selfCheckResult">
            <div class="selfcheck-overview" :class="'status-' + selfCheckResult.overall">
              <div class="sc-score">
                <div class="sc-score-num">{{ selfCheckResult.pass_rate }}%</div>
                <div class="sc-score-label">通过率</div>
              </div>
              <div class="sc-info">
                <div class="sc-title">{{ selfCheckResult.overall === 'healthy' ? '一切正常' : (selfCheckResult.overall === 'warning' ? '存在警告' : '严重异常') }}</div>
                <div class="sc-detail">{{ selfCheckResult.passed }} / {{ selfCheckResult.total }} 项通过 · 耗时 {{ selfCheckResult.elapsed_ms }}ms</div>
                <div class="sc-time">{{ selfCheckResult.checked_at }}</div>
              </div>
            </div>
            <div class="check-result-list">
              <div v-for="(c, idx) in selfCheckResult.checks" :key="idx" class="check-result-item" :class="{ fail: !c.passed }">
                <div class="cr-status">
                  <el-icon :size="20" :color="c.passed ? '#25D07D' : '#f56c6c'">
                    <CircleCheck v-if="c.passed" /><CircleClose v-else />
                  </el-icon>
                </div>
                <div class="cr-name">{{ c.name }}</div>
                <div class="cr-detail">
                  <template v-if="c.passed && c.detail">
                    <el-tag v-for="(v, k) in c.detail" :key="k" size="small" effect="light" type="info">{{ k }}: {{ v }}</el-tag>
                  </template>
                  <template v-else-if="!c.passed"><span class="cr-error">{{ c.error }}</span></template>
                </div>
              </div>
            </div>
          </div>
          <div class="panel-card__body empty-hint" v-else>
            <el-icon :size="48" color="#606266"><Monitor /></el-icon>
            <div style="margin-top:12px;">点击"运行自检"检测系统各项功能</div>
            <div style="margin-top:8px;color:#909399;font-size:13px;">包括：模块导入、数据库、策略引擎、新闻分析、代理管理、交易所客户端等</div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="运行日志" name="logs">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">日志查看器</span>
            <div class="log-controls">
              <el-select v-model="logFilter.type" size="default" style="width:100px;" @change="loadLogs">
                <el-option label="应用日志" value="app" />
                <el-option label="错误日志" value="error" />
                <el-option label="交易日志" value="trade" />
              </el-select>
              <el-select v-model="logFilter.level" size="default" style="width:100px;" @change="loadLogs" clearable>
                <el-option label="DEBUG" value="DEBUG" />
                <el-option label="INFO" value="INFO" />
                <el-option label="WARNING" value="WARNING" />
                <el-option label="ERROR" value="ERROR" />
              </el-select>
              <el-input v-model="logFilter.keyword" placeholder="搜索关键词..." size="default" style="width:180px;" clearable @keyup.enter="loadLogs" />
              <el-button :icon="Refresh" @click="loadLogs" :loading="logLoading">刷新</el-button>
            </div>
          </div>
          <div class="panel-card__body log-viewer">
            <div v-loading="logLoading" class="log-content">
              <div v-if="!logEntries.length && !logLoading" class="empty-hint">暂无日志记录</div>
              <div v-for="(entry, idx) in logEntries" :key="idx" class="log-line" :class="'level-' + entry.level">
                <span class="log-time">{{ entry.timestamp }}</span>
                <span class="log-level" :class="'tag-' + entry.level">{{ entry.level }}</span>
                <span class="log-module">{{ entry.module }}:{{ entry.function }}:{{ entry.line }}</span>
                <span class="log-message">{{ entry.message }}</span>
              </div>
            </div>
            <div class="log-pagination" v-if="logTotal > 0">
              <el-pagination v-model:current-page="logFilter.page" v-model:page-size="logFilter.page_size" :total="logTotal" layout="prev, pager, next, total" :page-sizes="[50, 100, 200]" @current-change="loadLogs" @size-change="loadLogs" small />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- AI 控制中心 -->
      <el-tab-pane label="🤖 AI控制中心" name="ai-control">
        <div class="ai-control-wrap">
          <!-- 任务类型卡片 -->
          <div class="ai-task-grid">
            <div class="ai-task-card" v-for="cfg in TASK_CONFIG" :key="cfg.type" @click="openTaskModal(cfg.type)">
              <div class="ai-task-icon" :style="{ background: cfg.color + '20', color: cfg.color }">
                {{ cfg.icon }}
              </div>
              <div class="ai-task-name">{{ cfg.name }}</div>
              <div class="ai-task-desc">{{ cfg.desc }}</div>
            </div>
          </div>

          <!-- 任务列表 -->
          <div class="ai-task-list-section">
            <div class="ai-task-list-header">
              <span class="section-title">📋 任务列表</span>
              <div class="sse-status">
                <span class="sse-dot" :class="{ active: sseActiveCount > 0 }"></span>
                <span>{{ sseActiveCount > 0 ? '实时推送中 (' + sseActiveCount + ')' : '就绪' }}</span>
              </div>
            </div>
            <div v-if="aiTasks.length === 0" class="ai-empty">
              <el-empty description="暂无任务，点击上方卡片创建" :image-size="60" />
            </div>
            <div v-else class="ai-task-list">
              <div v-for="task in aiTasks" :key="task.task_id" class="ai-task-item" @click="showTaskDetail(task)">
                <div class="ati-header">
                  <span class="ati-name">{{ task.type_label }}</span>
                  <el-tag size="small" effect="dark" :type="taskStatusType(task.status)">
                    {{ taskStatusText(task.status) }}
                  </el-tag>
                </div>
                <div class="ati-meta">
                  <span>{{ task.params.symbol || task.params.test_symbol || '多币种' }}</span>
                  <span>{{ formatTime(task.created_at) }}</span>
                  <span v-if="task.duration_seconds">{{ task.duration_seconds.toFixed(1) }}s</span>
                </div>
                <div class="ati-progress">
                  <el-progress :percentage="task.progress" :stroke-width="6" :show-text="false"
                    :color="task.status === 'failed' ? '#f56c6c' : '#25D07D'" />
                  <span class="ati-pct">{{ task.progress }}%</span>
                </div>
                <div v-if="task.error" class="ati-error">{{ task.error }}</div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 交易引擎总览 -->
      <el-tab-pane label="⚡ 引擎总览" name="engine">
        <div class="engine-overview-wrap">
          <!-- 顶部状态条 -->
          <div class="engine-top-bar">
            <div class="engine-status-badge" :class="{ running: engineData?.score_engine?.is_running }">
              <span class="status-light" :class="engineData?.score_engine?.is_running ? 'ok' : 'idle'"></span>
              <span>{{ engineData?.score_engine?.is_running ? '引擎运行中' : '引擎未启动' }}</span>
            </div>
            <div class="engine-refresh">
              <el-icon :size="14" :class="{ 'rotating': engineLoading }" @click="loadEngineOverview"><Refresh /></el-icon>
              <span>自动刷新中 (5s)</span>
            </div>
            <div class="engine-update-time">
              数据时间：{{ engineData ? formatTime(engineData.generated_at) : '--' }}
            </div>
          </div>

          <!-- 核心指标卡片 -->
          <div class="engine-stat-grid">
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(37,208,125,0.15);color:#25D07D">📊</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.strategies?.active || 0 }}</div>
                <div class="esc-label">活跃策略</div>
                <div class="esc-sub">共 {{ engineData?.strategies?.total || 0 }} 个策略</div>
              </div>
            </div>
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(96,165,250,0.15);color:#60A5FA">💼</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.positions?.open_count || 0 }}</div>
                <div class="esc-label">当前持仓</div>
                <div class="esc-sub" :class="(engineData?.positions?.total_unrealized_pnl || 0) >= 0 ? 'profit' : 'loss'">
                  {{ (engineData?.positions?.total_unrealized_pnl || 0) >= 0 ? '+' : '' }}${{ formatNumber(engineData?.positions?.total_unrealized_pnl) }}
                </div>
              </div>
            </div>
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(251,191,36,0.15);color:#FBBF24">📈</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.orders?.today_total || 0 }}</div>
                <div class="esc-label">今日订单</div>
                <div class="esc-sub">成交 {{ engineData?.orders?.today_filled || 0 }} 笔</div>
              </div>
            </div>
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(167,139,250,0.15);color:#A78BFA">🧠</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.score_engine?.today_records || 0 }}</div>
                <div class="esc-label">今日评分</div>
                <div class="esc-sub">近1h {{ engineData?.score_engine?.last_hour_records || 0 }} 条</div>
              </div>
            </div>
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(248,113,113,0.15);color:#F87171">📰</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.news?.today_count || 0 }}</div>
                <div class="esc-label">今日新闻</div>
                <div class="esc-sub">重要 {{ engineData?.news?.last_24h_important || 0 }} 条</div>
              </div>
            </div>
            <div class="engine-stat-card">
              <div class="esc-icon" style="background:rgba(56,189,248,0.15);color:#38BDF8">🤖</div>
              <div class="esc-info">
                <div class="esc-value">{{ engineData?.ai_analysis?.today_count || 0 }}</div>
                <div class="esc-label">AI分析</div>
                <div class="esc-sub">今日已分析</div>
              </div>
            </div>
          </div>

          <!-- 双栏布局 -->
          <div class="engine-two-col">
            <!-- 左侧：定时任务状态 + 策略分布 -->
            <div class="engine-col">
              <!-- 定时任务状态 -->
              <div class="panel-card">
                <div class="panel-card__header">
                  <span class="panel-card__title">⚙️ 定时任务状态</span>
                  <el-tag size="small" effect="dark" :type="schedulerData?.running ? 'success' : 'info'">
                    {{ schedulerData?.running ? '运行中' : '已停止' }}
                  </el-tag>
                </div>
                <div class="panel-card__body">
                  <div v-if="schedulerData?.tasks?.length" class="sched-task-list">
                    <div v-for="task in schedulerData.tasks" :key="task.id" class="sched-task-item">
                      <span class="st-icon">{{ task.icon }}</span>
                      <div class="st-info">
                        <div class="st-name">{{ task.name }}</div>
                        <div class="st-interval">{{ task.interval }}</div>
                      </div>
                      <div class="st-status">
                        <span class="status-light ok" title="运行中"></span>
                        <span class="st-next-run" v-if="task.next_run_time">下次: {{ formatTime(task.next_run_time) }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-else class="empty-hint">
                    <el-empty description="定时任务未启动" :image-size="50" />
                  </div>
                </div>
              </div>

              <!-- 策略运行模式分布 -->
              <div class="panel-card">
                <div class="panel-card__header">
                  <span class="panel-card__title">🎯 策略运行模式</span>
                  <span class="status-light ok" style="margin:0;"></span>
                </div>
                <div class="panel-card__body">
                  <div class="strategy-mode-bars">
                    <div class="smb-item">
                      <div class="smb-label">
                        <span>🤖 全自动</span>
                        <span class="smb-count">{{ engineData?.strategies?.auto || 0 }}</span>
                      </div>
                      <el-progress :percentage="modePct('auto')" :stroke-width="12" :show-text="false" color="#25D07D" />
                    </div>
                    <div class="smb-item">
                      <div class="smb-label">
                        <span>⚡ 半自动</span>
                        <span class="smb-count">{{ engineData?.strategies?.semi_auto || 0 }}</span>
                      </div>
                      <el-progress :percentage="modePct('semi_auto')" :stroke-width="12" :show-text="false" color="#FBBF24" />
                    </div>
                    <div class="smb-item">
                      <div class="smb-label">
                        <span>🔬 模拟盘</span>
                        <span class="smb-count">{{ engineData?.strategies?.simulate || 0 }}</span>
                      </div>
                      <el-progress :percentage="modePct('simulate')" :stroke-width="12" :show-text="false" color="#60A5FA" />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右侧：当前持仓 + 品种评分 -->
            <div class="engine-col">
              <!-- 当前持仓 -->
              <div class="panel-card">
                <div class="panel-card__header">
                  <span class="panel-card__title">💼 当前持仓</span>
                  <span class="status-light" :class="engineData?.positions?.open_count > 0 ? 'ok' : 'idle'" style="margin:0;"></span>
                  <span class="panel-card__subtitle">{{ engineData?.positions?.open_count || 0 }} 个持仓</span>
                </div>
                <div class="panel-card__body">
                  <div v-if="engineData?.positions?.details?.length" class="position-list">
                    <div v-for="pos in engineData.positions.details" :key="pos.symbol + pos.side" class="pos-item">
                      <div class="pos-left">
                        <span class="pos-symbol">{{ pos.symbol }}</span>
                        <el-tag size="small" effect="dark" :type="pos.side === 1 ? 'success' : 'danger'">
                          {{ pos.side === 1 ? '多' : '空' }} {{ pos.leverage }}x
                        </el-tag>
                      </div>
                      <div class="pos-right">
                        <span class="pos-pnl" :class="pos.unrealized_pnl >= 0 ? 'profit' : 'loss'">
                          {{ pos.unrealized_pnl >= 0 ? '+' : '' }}${{ formatNumber(pos.unrealized_pnl) }}
                        </span>
                        <span class="pos-pct" :class="pos.pnl_ratio >= 0 ? 'profit' : 'loss'">
                          {{ pos.pnl_ratio >= 0 ? '+' : '' }}{{ pos.pnl_ratio?.toFixed(2) }}%
                        </span>
                      </div>
                    </div>
                  </div>
                  <div v-else class="empty-hint">
                    <el-empty description="暂无持仓" :image-size="50" />
                  </div>
                </div>
              </div>

              <!-- 品种评分总览 -->
              <div class="panel-card">
                <div class="panel-card__header">
                  <span class="panel-card__title">📊 品种评分总览</span>
                  <span class="panel-card__subtitle">最近一次评分快照</span>
                </div>
                <div class="panel-card__body">
                  <div v-if="engineData?.symbol_scores?.length" class="symbol-score-list">
                    <div v-for="ss in engineData.symbol_scores" :key="ss.symbol + ss.timeframe" class="ss-item">
                      <div class="ss-header">
                        <span class="ss-symbol">{{ ss.symbol }}</span>
                        <el-tag size="small" effect="plain">{{ ss.timeframe }}</el-tag>
                        <span class="ss-score" :class="scoreClass(ss.score_total)">
                          {{ ss.score_total?.toFixed(1) }}
                        </span>
                      </div>
                      <div class="ss-bar">
                        <div class="ss-bar-fill" :class="scoreClass(ss.score_total)"
                          :style="{ width: (ss.score_total * 10) + '%' }"></div>
                      </div>
                      <div class="ss-detail">
                        <span>技术 {{ ss.score_technical?.toFixed(1) }}</span>
                        <span>新闻 {{ ss.score_news?.toFixed(1) }}</span>
                        <span>AI {{ ss.score_ai?.toFixed(1) }}</span>
                        <span :class="ss.direction === 'long' ? 'profit' : ss.direction === 'short' ? 'loss' : ''">
                          {{ ss.direction === 'long' ? '看涨' : ss.direction === 'short' ? '看跌' : '中性' }}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div v-else class="empty-hint">
                    <el-empty description="暂无评分数据" :image-size="50" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 最近交易记录 -->
          <div class="panel-card">
            <div class="panel-card__header">
              <span class="panel-card__title">📋 最近交易记录</span>
              <span class="status-light ok" style="margin:0;"></span>
              <span class="panel-card__subtitle">最近10笔</span>
            </div>
            <div class="panel-card__body">
              <el-table :data="engineData?.recent_orders || []" size="small" style="width: 100%" stripe>
                <el-table-column prop="symbol" label="品种" width="90" />
                <el-table-column label="方向" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" effect="dark" :type="row.side === 1 ? 'success' : 'danger'">
                      {{ row.side === 1 ? '做多' : '做空' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" effect="plain" :type="row.order_type === 1 ? 'primary' : 'warning'">
                      {{ row.order_type === 1 ? '开仓' : '平仓' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="{ row }">
                    <el-tag size="small" effect="dark" :type="orderStatusType(row.status)">
                      {{ orderStatusText(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="触发原因" width="120">
                  <template #default="{ row }">
                    {{ triggerReasonText(row.trigger_reason) }}
                  </template>
                </el-table-column>
                <el-table-column label="金额(USDT)" width="120" align="right">
                  <template #default="{ row }">
                    ${{ formatNumber(row.quantity_usdt) }}
                  </template>
                </el-table-column>
                <el-table-column label="已实现盈亏" width="130" align="right">
                  <template #default="{ row }">
                    <span v-if="row.order_type === 2" :class="row.realized_pnl >= 0 ? 'profit' : 'loss'">
                      {{ row.realized_pnl >= 0 ? '+' : '' }}${{ formatNumber(row.realized_pnl) }}
                    </span>
                    <span v-else>--</span>
                  </template>
                </el-table-column>
                <el-table-column label="时间" width="170">
                  <template #default="{ row }">
                    {{ formatTime(row.created_at) }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="分享链接" name="share">
        <div class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">分享诊断链接</span>
            <el-button type="primary" :icon="Plus" @click="showShareDialog = true">创建分享链接</el-button>
          </div>
          <div class="panel-card__body">
            <div class="share-hint">
              <el-icon><InfoFilled /></el-icon>
              <span>生成分享链接后，可将链接发给开发者，开发者无需登录即可查看系统状态和日志，便于快速定位问题。</span>
            </div>
            <div v-if="shareTokens.length" class="share-list">
              <div v-for="t in shareTokens" :key="t.token" class="share-item">
                <div class="share-info">
                  <div class="share-token">{{ t.token }}</div>
                  <div class="share-meta">创建于 {{ t.created_at }} · 有效期 {{ t.ttl_hours }}小时 · 访问 {{ t.access_count }}次</div>
                </div>
                <div class="share-actions">
                  <el-button size="small" type="primary" text @click="copyShareUrl(t)">复制链接</el-button>
                  <el-button size="small" type="danger" text @click="revokeToken(t)">撤销</el-button>
                </div>
              </div>
            </div>
            <div v-else class="empty-hint">
              <el-icon :size="40" color="#909399"><Link /></el-icon>
              <div style="margin-top:12px;">暂无分享链接</div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- AI 任务创建弹窗 -->
    <el-dialog v-model="showTaskModal" :title="currentTaskConfig?.name || '创建任务'" width="520px">
      <div v-if="currentTaskConfig" class="task-create-form">
        <div class="form-item" v-if="currentTaskConfig.fields.includes('symbol')">
          <label>交易品种</label>
          <el-input v-model="taskForm.symbol" placeholder="如 BTC/USDT" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('timeframe')">
          <label>时间级别</label>
          <el-select v-model="taskForm.timeframe" style="width:100%;">
            <el-option label="1分钟" value="1m" />
            <el-option label="5分钟" value="5m" />
            <el-option label="15分钟" value="15m" />
            <el-option label="1小时" value="1h" />
            <el-option label="4小时" value="4h" />
            <el-option label="日线" value="1d" />
          </el-select>
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('strategy')">
          <label>策略类型</label>
          <el-select v-model="taskForm.strategy" style="width:100%;">
            <el-option label="EMV 简易波动" value="emv" />
            <el-option label="MACD 趋势" value="macd" />
            <el-option label="RSI 超买超卖" value="rsi" />
            <el-option label="布林带" value="bollinger" />
            <el-option label="网格策略" value="grid" />
          </el-select>
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('days')">
          <label>回测天数</label>
          <el-input-number v-model="taskForm.days" :min="7" :max="365" style="width:100%;" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('initial_capital')">
          <label>初始资金 (USDT)</label>
          <el-input-number v-model="taskForm.initial_capital" :min="1000" :max="1000000" :step="1000" style="width:100%;" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('symbols')">
          <label>扫描币种 (逗号分隔)</label>
          <el-input v-model="taskForm.symbols" type="textarea" :rows="2" placeholder="BTC/USDT, ETH/USDT, SOL/USDT" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('timeframes')">
          <label>扫描时间级别 (逗号分隔)</label>
          <el-input v-model="taskForm.timeframes" placeholder="15m, 1h, 4h" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('top_n')">
          <label>返回 Top N 机会</label>
          <el-input-number v-model="taskForm.top_n" :min="3" :max="50" style="width:100%;" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('analysis_type')">
          <label>分析类型</label>
          <el-select v-model="taskForm.analysis_type" style="width:100%;">
            <el-option label="综合分析" value="comprehensive" />
            <el-option label="技术面分析" value="technical" />
            <el-option label="情绪面分析" value="sentiment" />
            <el-option label="风险评估" value="risk" />
          </el-select>
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('test_symbol')">
          <label>测试币种</label>
          <el-input v-model="taskForm.test_symbol" placeholder="如 BTC/USDT" />
        </div>
        <div class="form-item" v-if="currentTaskConfig.fields.includes('test_timeframe')">
          <label>测试时间级别</label>
          <el-select v-model="taskForm.test_timeframe" style="width:100%;">
            <el-option label="15分钟" value="15m" />
            <el-option label="1小时" value="1h" />
            <el-option label="4小时" value="4h" />
          </el-select>
        </div>
      </div>
      <template #footer>
        <el-button @click="showTaskModal = false">取消</el-button>
        <el-button type="primary" :loading="taskCreating" @click="submitTask">开始执行</el-button>
      </template>
    </el-dialog>

    <!-- AI 任务详情弹窗 -->
    <el-dialog v-model="showDetailModal" :title="detailTitle" width="700px" top="5vh">
      <div class="task-detail-content" v-html="detailContent"></div>
      <template #footer>
        <el-button @click="showDetailModal = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showShareDialog" title="创建分享链接" width="480px">
      <div class="share-create-form">
        <div class="form-item">
          <label>有效期</label>
          <el-select v-model="newShareTtl" style="width:100%;">
            <el-option label="1小时" :value="1" />
            <el-option label="6小时" :value="6" />
            <el-option label="24小时（推荐）" :value="24" />
            <el-option label="72小时" :value="72" />
            <el-option label="7天" :value="168" />
          </el-select>
        </div>
        <div class="form-tip">
          <el-icon><Warning /></el-icon>
          <span>分享链接包含系统状态和错误日志，请勿公开传播，仅发给信任的开发者。</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="showShareDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingShare" @click="createShare">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Monitor, CircleCheck, CircleClose, Warning, Link, Plus, Coin, Lightning, Timer, InfoFilled } from '@element-plus/icons-vue'
import { http } from '@/utils/request'
import { API_PREFIX } from '@/utils/env'

const activeTab = ref('status')
const refreshing = ref(false)
const checking = ref(false)

// ============ AI 控制中心 ============
const aiTasks = ref([])
const showTaskModal = ref(false)
const showDetailModal = ref(false)
const detailTitle = ref('')
const detailContent = ref('')
const taskCreating = ref(false)
const currentTaskType = ref('')
const taskForm = reactive({
  symbol: 'BTC/USDT',
  timeframe: '1h',
  strategy: 'emv',
  days: 90,
  initial_capital: 10000,
  symbols: 'BTC/USDT,ETH/USDT,SOL/USDT,SAND/USDT,HBAR/USDT,BNB/USDT,XRP/USDT',
  timeframes: '15m,1h,4h',
  top_n: 10,
  analysis_type: 'comprehensive',
  test_symbol: 'BTC/USDT',
  test_timeframe: '1h',
})
const sseConnections = reactive({}) // task_id -> EventSource

const TASK_CONFIG = {
  backtest: {
    type: 'backtest', name: '模拟回测', icon: '📈', color: '#25D07D',
    desc: '单币种策略历史回测，验证策略有效性',
    endpoint: '/monitor/ai/tasks/backtest',
    fields: ['symbol', 'timeframe', 'strategy', 'days', 'initial_capital'],
  },
  strategy_scan: {
    type: 'strategy_scan', name: '策略扫描', icon: '🔍', color: '#3B82F6',
    desc: '多币种多时间级别批量扫描，发现交易机会',
    endpoint: '/monitor/ai/tasks/strategy-scan',
    fields: ['symbols', 'timeframes', 'strategy', 'top_n'],
  },
  ai_analysis: {
    type: 'ai_analysis', name: 'AI市场分析', icon: '🧠', color: '#8B5CF6',
    desc: '技术面+情绪面+风险评估综合分析',
    endpoint: '/monitor/ai/tasks/ai-analysis',
    fields: ['symbol', 'analysis_type'],
  },
  full_test: {
    type: 'full_test', name: '全面测试', icon: '⚡', color: '#F59E0B',
    desc: '回测+扫描+AI分析一站式全面诊断',
    endpoint: '/monitor/ai/tasks/full-test',
    fields: ['test_symbol', 'test_timeframe', 'strategy'],
  },
}

const currentTaskConfig = computed(() => TASK_CONFIG[currentTaskType.value])

const sseActiveCount = computed(() => Object.keys(sseConnections).length)

function taskStatusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running' || status === 'pending') return 'warning'
  return 'info'
}

function taskStatusText(status) {
  const map = { pending: '等待中', running: '运行中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

function openTaskModal(type) {
  currentTaskType.value = type
  showTaskModal.value = true
}

async function submitTask() {
  if (!currentTaskConfig.value) return
  taskCreating.value = true
  try {
    let payload = { ...taskForm }
    // 全面测试任务：参数名适配
    if (currentTaskType.value === 'full_test') {
      payload = {
        symbols: [taskForm.test_symbol],
        timeframes: [taskForm.test_timeframe],
        strategy: taskForm.strategy,
      }
    }
    // 策略扫描任务：字符串转数组
    if (currentTaskType.value === 'strategy_scan') {
      payload.symbols = taskForm.symbols.split(',').map(s => s.trim()).filter(Boolean)
      payload.timeframes = taskForm.timeframes.split(',').map(s => s.trim()).filter(Boolean)
      payload.top_n = taskForm.top_n
      payload.strategy = taskForm.strategy
    }
    const r = await http.post(API_PREFIX + currentTaskConfig.value.endpoint, payload)
    showTaskModal.value = false
    ElMessage.success('任务已启动')
    loadAiTasks()
    // 建立 SSE 连接
    setupTaskSse(r.task_id)
  } catch (e) {
    ElMessage.error('创建失败: ' + (e.message || e))
  } finally {
    taskCreating.value = false
  }
}

async function loadAiTasks() {
  try {
    const r = await http.get(API_PREFIX + '/monitor/ai/tasks')
    aiTasks.value = r.tasks || []
    ensureSseForRunningTasks()
  } catch (e) {
    console.error('加载任务失败', e)
  }
}

function setupTaskSse(taskId) {
  if (!taskId || sseConnections[taskId]) return
  const url = API_PREFIX + '/monitor/ai/tasks/' + taskId + '/stream'
  const es = new EventSource(url)
  sseConnections[taskId] = es

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      handleSseEvent(data)
    } catch (e) { console.error('SSE parse error', e) }
  }
  es.onerror = () => {
    closeTaskSse(taskId)
    setTimeout(() => {
      const task = aiTasks.value.find(t => t.task_id === taskId)
      if (task && (task.status === 'running' || task.status === 'pending')) {
        setupTaskSse(taskId)
      }
    }, 3000)
  }
}

function closeTaskSse(taskId) {
  if (sseConnections[taskId]) {
    try { sseConnections[taskId].close() } catch (e) {}
    delete sseConnections[taskId]
  }
}

function handleSseEvent(event) {
  const taskId = event.task_id
  const idx = aiTasks.value.findIndex(t => t.task_id === taskId)
  if (idx === -1) { loadAiTasks(); return }
  const task = aiTasks.value[idx]
  if (event.event === 'progress') {
    task.progress = event.data.progress
    task.status = event.data.status
  } else if (event.event === 'completed') {
    task.progress = 100
    task.status = 'completed'
    task.result = event.data.result
    task.completed_at = event.timestamp
    closeTaskSse(taskId)
    if (showDetailModal.value && detailTitle.value.includes(task.type_label)) {
      detailContent.value = renderTaskDetailHtml(task)
    }
  } else if (event.event === 'failed') {
    task.progress = event.data.progress || task.progress
    task.status = 'failed'
    task.error = event.data.error
    task.completed_at = event.timestamp
    closeTaskSse(taskId)
  }
}

function ensureSseForRunningTasks() {
  aiTasks.value.forEach(t => {
    if ((t.status === 'running' || t.status === 'pending') && !sseConnections[t.task_id]) {
      setupTaskSse(t.task_id)
    }
  })
  // 清理已完成的
  Object.keys(sseConnections).forEach(tid => {
    const t = aiTasks.value.find(x => x.task_id === tid)
    if (!t || (t.status !== 'running' && t.status !== 'pending')) {
      closeTaskSse(tid)
    }
  })
}

function showTaskDetail(task) {
  detailTitle.value = task.type_label + ' - 任务详情'
  detailContent.value = renderTaskDetailHtml(task)
  showDetailModal.value = true
}

function renderTaskDetailHtml(task) {
  let html = ''
  html += '<div style="margin-bottom:16px;"><div style="display:flex;justify-content:space-between;margin-bottom:8px;"><span style="color:#7A8A9A;font-size:13px;">任务ID</span><span style="font-family:monospace;font-size:13px;">' + task.task_id + '</span></div>'
  html += '<div style="display:flex;justify-content:space-between;margin-bottom:8px;"><span style="color:#7A8A9A;font-size:13px;">状态</span><span style="font-size:13px;">' + taskStatusText(task.status) + '</span></div>'
  html += '<div style="display:flex;justify-content:space-between;margin-bottom:8px;"><span style="color:#7A8A9A;font-size:13px;">创建时间</span><span style="font-size:13px;">' + (task.created_at || '') + '</span></div>'
  if (task.duration_seconds) {
    html += '<div style="display:flex;justify-content:space-between;"><span style="color:#7A8A9A;font-size:13px;">耗时</span><span style="font-size:13px;">' + task.duration_seconds.toFixed(1) + 's</span></div>'
  }
  html += '</div>'

  if (task.status === 'failed') {
    html += '<div style="background:rgba(245,108,108,0.1);padding:12px;border-radius:8px;color:#f56c6c;font-size:13px;margin-bottom:16px;">错误: ' + task.error + '</div>'
  }

  if (task.result && task.task_type === 'backtest') {
    const s = task.result.summary || task.result
    html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">📊 回测结果</div>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">总收益率</div><div style="font-size:18px;font-weight:700;' + (s.total_return_pct >= 0 ? 'color:#25D07D' : 'color:#f56c6c') + ';">' + (s.total_return_pct >= 0 ? '+' : '') + s.total_return_pct + '%</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">夏普比率</div><div style="font-size:18px;font-weight:700;color:#CBD5E1;">' + s.sharpe_ratio + '</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">最大回撤</div><div style="font-size:18px;font-weight:700;color:#f56c6c;">-' + s.max_drawdown + '%</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">胜率</div><div style="font-size:18px;font-weight:700;color:#25D07D;">' + (s.win_rate * 100).toFixed(0) + '%</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">交易次数</div><div style="font-size:18px;font-weight:700;color:#CBD5E1;">' + s.total_trades + '</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">盈亏比</div><div style="font-size:18px;font-weight:700;color:#CBD5E1;">' + s.profit_factor + '</div></div>'
    html += '</div></div>'

    if (task.result.top_trades && task.result.top_trades.length) {
      html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">📝 近期交易</div>'
      html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="background:#0A131B;">'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">方向</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">入场价</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">出场价</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">盈亏%</th>'
      html += '</tr></thead><tbody>'
      task.result.top_trades.slice(0, 5).forEach(t => {
        html += '<tr style="border-bottom:1px solid #0F1A24;">'
        html += '<td style="padding:8px;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:' + (t.side === 'long' ? 'rgba(37,208,125,0.15)' : 'rgba(245,108,108,0.15)') + ';color:' + (t.side === 'long' ? '#25D07D' : '#f56c6c') + ';">' + (t.side === 'long' ? '多' : '空') + '</span></td>'
        html += '<td style="padding:8px;color:#CBD5E1;">$' + t.entry_price + '</td>'
        html += '<td style="padding:8px;color:#CBD5E1;">$' + t.exit_price + '</td>'
        html += '<td style="padding:8px;' + (t.pnl_pct >= 0 ? 'color:#25D07D' : 'color:#f56c6c') + ';">' + (t.pnl_pct >= 0 ? '+' : '') + t.pnl_pct + '%</td>'
        html += '</tr>'
      })
      html += '</tbody></table></div>'
    }

    if (task.result.conclusion) {
      html += '<div style="background:linear-gradient(135deg,rgba(37,208,125,0.08),rgba(59,130,246,0.08));border:1px solid rgba(37,208,125,0.2);border-radius:10px;padding:14px 18px;">'
      html += '<div style="font-size:13px;font-weight:600;color:#25D07D;margin-bottom:6px;">💡 AI 结论</div>'
      html += '<div style="font-size:13px;color:#CBD5E1;line-height:1.7;">' + task.result.conclusion + '</div></div>'
    }
  } else if (task.result && task.task_type === 'strategy_scan') {
    const s = task.result.summary || {}
    html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">🔍 扫描结果</div>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">扫描组合</div><div style="font-size:18px;font-weight:700;color:#CBD5E1;">' + (s.total_scanned || 0) + '</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">平均评分</div><div style="font-size:18px;font-weight:700;color:#25D07D;">' + (s.avg_score || 0).toFixed(1) + '</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">看涨信号</div><div style="font-size:18px;font-weight:700;color:#25D07D;">' + (s.bullish_count || 0) + '</div></div>'
    html += '</div></div>'

    if (task.result.opportunities && task.result.opportunities.length) {
      html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">⭐ Top 机会</div>'
      html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="background:#0A131B;">'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">品种</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">周期</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">评分</th>'
      html += '<th style="padding:8px;text-align:left;color:#7A8A9A;font-weight:500;">信号</th>'
      html += '</tr></thead><tbody>'
      task.result.opportunities.slice(0, 10).forEach(o => {
        html += '<tr style="border-bottom:1px solid #0F1A24;">'
        html += '<td style="padding:8px;color:#E6EDF3;font-weight:600;">' + o.symbol + '</td>'
        html += '<td style="padding:8px;color:#CBD5E1;">' + o.timeframe + '</td>'
        html += '<td style="padding:8px;color:#25D07D;font-weight:600;">' + o.score + '</td>'
        html += '<td style="padding:8px;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:rgba(37,208,125,0.15);color:#25D07D;">' + o.signal + '</span></td>'
        html += '</tr>'
      })
      html += '</tbody></table></div>'
    }
  } else if (task.result && task.task_type === 'ai_analysis') {
    const a = task.result
    html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">🧠 AI 分析结果</div>'
    if (a.trend) {
      html += '<div style="background:#0A131B;padding:12px;border-radius:8px;margin-bottom:10px;"><div style="font-size:12px;color:#7A8A9A;margin-bottom:6px;">趋势判断</div>'
      html += '<div style="font-size:15px;font-weight:700;color:' + (a.trend.direction === 'bullish' ? '#25D07D' : a.trend.direction === 'bearish' ? '#f56c6c' : '#CBD5E1') + ';">' + (a.trend.direction === 'bullish' ? '📈 看涨' : a.trend.direction === 'bearish' ? '📉 看跌' : '➡️ 震荡') + ' (' + a.trend.strength + '/10)</div></div>'
    }
    if (a.technical) {
      html += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:10px;">'
      html += '<div style="background:#0A131B;padding:12px;border-radius:8px;"><div style="font-size:12px;color:#7A8A9A;">RSI</div><div style="font-size:16px;font-weight:700;color:#CBD5E1;">' + a.technical.rsi + '</div></div>'
      html += '<div style="background:#0A131B;padding:12px;border-radius:8px;"><div style="font-size:12px;color:#7A8A9A;">恐慌贪婪指数</div><div style="font-size:16px;font-weight:700;color:#F59E0B;">' + a.sentiment?.fear_greed_index + '</div></div>'
      html += '</div>'
    }
    if (a.key_levels) {
      html += '<div style="background:#0A131B;padding:12px;border-radius:8px;margin-bottom:10px;"><div style="font-size:12px;color:#7A8A9A;margin-bottom:6px;">关键价位</div>'
      html += '<div style="display:flex;justify-content:space-between;"><span>支撑: <strong style="color:#f56c6c;">$' + a.key_levels.support + '</strong></span><span>阻力: <strong style="color:#25D07D;">$' + a.key_levels.resistance + '</strong></span></div></div>'
    }
    if (a.risk_assessment) {
      html += '<div style="background:#0A131B;padding:12px;border-radius:8px;margin-bottom:10px;"><div style="font-size:12px;color:#7A8A9A;margin-bottom:6px;">风险评估</div>'
      html += '<div style="font-size:14px;color:#CBD5E1;">整体风险: <strong>' + a.risk_assessment.overall_risk + '</strong></div>'
      html += '<div style="font-size:13px;color:#7A8A9A;margin-top:4px;">预期回撤: ' + a.risk_assessment.expected_drawdown + '</div></div>'
    }
    html += '</div>'
    if (a.conclusion) {
      html += '<div style="background:linear-gradient(135deg,rgba(37,208,125,0.08),rgba(59,130,246,0.08));border:1px solid rgba(37,208,125,0.2);border-radius:10px;padding:14px 18px;">'
      html += '<div style="font-size:13px;font-weight:600;color:#25D07D;margin-bottom:6px;">💡 AI 结论</div>'
      html += '<div style="font-size:13px;color:#CBD5E1;line-height:1.7;">' + a.conclusion + '</div></div>'
    }
  } else if (task.result && task.task_type === 'full_test') {
    const f = task.result
    html += '<div style="margin-bottom:16px;"><div style="font-size:14px;font-weight:600;margin-bottom:10px;">⚡ 全面测试结果</div>'
    html += '<div style="background:linear-gradient(135deg,rgba(37,208,125,0.1),rgba(245,158,11,0.1));padding:16px;border-radius:10px;text-align:center;margin-bottom:12px;">'
    html += '<div style="font-size:12px;color:#7A8A9A;">综合评分</div>'
    html += '<div style="font-size:32px;font-weight:700;color:#25D07D;">' + f.overall_score + '/100</div></div>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">回测收益</div><div style="font-size:16px;font-weight:700;color:' + ((f.backtest_result?.summary?.total_return_pct || 0) >= 0 ? '#25D07D' : '#f56c6c') + ';">' + ((f.backtest_result?.summary?.total_return_pct || 0) >= 0 ? '+' : '') + (f.backtest_result?.summary?.total_return_pct || 0) + '%</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">扫描机会</div><div style="font-size:16px;font-weight:700;color:#3B82F6;">' + (f.scan_result?.opportunities?.length || 0) + '个</div></div>'
    html += '<div style="background:#0A131B;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:12px;color:#7A8A9A;">趋势判断</div><div style="font-size:16px;font-weight:700;color:#25D07D;">' + (f.ai_result?.trend?.direction || '-') + '</div></div>'
    html += '</div></div>'
  }

  if (!task.result && task.status !== 'failed' && (task.status === 'running' || task.status === 'pending')) {
    html += '<div style="text-align:center;padding:30px;color:#7A8A9A;">任务执行中，请等待完成...</div>'
  }
  return html
}

function formatTime(t) {
  if (!t) return ''
  return t.replace('T', ' ').substring(0, 19)
}
const status = reactive({
  overall: 'unknown',
  version: '1.2.0',
  uptime_seconds: 0,
  resources: null,
  database: {},
  redis: {},
  scheduler: {},
  logs: {},
  issues: [],
  issue_count: {},
})

const statusText = computed(() => {
  const map = { healthy: '系统运行正常', warning: '存在警告', critical: '系统异常', unknown: '加载中...' }
  return map[status.overall] || '未知'
})

const statusDesc = computed(() => {
  if (status.overall === 'healthy') return '所有服务运行良好'
  if (status.overall === 'warning') return '存在非关键问题，建议检查'
  if (status.overall === 'critical') return '存在严重问题，请立即处理'
  return '正在获取系统状态...'
})

function getResourceClass(val, warn, crit) {
  if (val >= crit) return 'critical'
  if (val >= warn) return 'warning'
  return 'normal'
}

function getProgressColor(val, warn, crit) {
  if (val >= crit) return '#f56c6c'
  if (val >= warn) return '#e6a23c'
  return '#25D07D'
}

function formatUptime(seconds) {
  if (!seconds) return '--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 24) {
    const d = Math.floor(h / 24)
    return d + '天' + (h % 24) + '小时'
  }
  return h + '小时' + m + '分'
}

async function refreshAll() {
  refreshing.value = true
  try { await loadStatus() } finally { refreshing.value = false }
}

async function loadStatus() {
  try {
    const res = await http.get(API_PREFIX + '/monitor/status')
    Object.assign(status, res)
  } catch (e) { console.error('加载状态失败:', e) }
}

const selfCheckResult = ref(null)
async function runSelfCheck() {
  checking.value = true
  try {
    const res = await http.get(API_PREFIX + '/monitor/self-check')
    selfCheckResult.value = res
    ElMessage.success('自检完成：' + res.pass_rate + '% 通过')
  } catch (e) { ElMessage.error('自检失败: ' + (e.message || e)) }
  finally { checking.value = false }
}

const logEntries = ref([])
const logTotal = ref(0)
const logLoading = ref(false)
const logFilter = reactive({ type: 'app', level: '', keyword: '', page: 1, page_size: 100 })

async function loadLogs() {
  logLoading.value = true
  try {
    const res = await http.get(API_PREFIX + '/monitor/logs', { params: {
      log_type: logFilter.type, level: logFilter.level, keyword: logFilter.keyword,
      page: logFilter.page, page_size: logFilter.page_size,
    }})
    logEntries.value = res.entries || []
    logTotal.value = res.total || 0
  } catch (e) { console.error('加载日志失败:', e) }
  finally { logLoading.value = false }
}

const showShareDialog = ref(false)
const newShareTtl = ref(24)
const creatingShare = ref(false)
const shareTokens = ref([])

async function loadShareTokens() {
  try {
    const res = await http.get(API_PREFIX + '/monitor/share/list')
    shareTokens.value = res.tokens || []
  } catch (e) { console.error('加载分享列表失败:', e) }
}

async function createShare() {
  creatingShare.value = true
  try {
    const res = await http.post(API_PREFIX + '/monitor/share', { ttl_hours: newShareTtl.value })
    showShareDialog.value = false
    await loadShareTokens()
    const url = window.location.origin + API_PREFIX + '/monitor/dashboard?token=' + res.token
    navigator.clipboard.writeText(url).then(() => {
      ElMessage.success('分享链接已创建并复制到剪贴板')
    }).catch(() => {
      ElMessage.success('分享链接已创建')
    })
  } catch (e) { ElMessage.error('创建失败: ' + (e.message || e)) }
  finally { creatingShare.value = false }
}

function copyShareUrl(token) {
  const url = window.location.origin + API_PREFIX + '/monitor/dashboard?token=' + token.token
  navigator.clipboard.writeText(url).then(() => { ElMessage.success('链接已复制到剪贴板') })
}

async function revokeToken(token) {
  try {
    await ElMessageBox.confirm('确定撤销此分享链接？撤销后链接将立即失效。', '确认', { type: 'warning' })
    await http.delete(API_PREFIX + '/monitor/share/' + token.token)
    ElMessage.success('已撤销')
    await loadShareTokens()
  } catch (e) { if (e !== 'cancel') { ElMessage.error('操作失败') } }
}

let autoRefreshTimer = null
function startAutoRefresh() {
  autoRefreshTimer = setInterval(() => {
    if (activeTab.value === 'status') loadStatus()
    if (activeTab.value === 'logs') loadLogs()
  }, 15000)
}

// ============ 交易引擎总览 ============
const engineData = ref(null)
const engineLoading = ref(false)
const schedulerData = ref(null)
let engineRefreshTimer = null

async function loadEngineOverview() {
  try {
    engineLoading.value = true
    const r = await http.get(`${API_PREFIX}/monitor/engine/overview`)
    engineData.value = r
  } catch (e) {
    console.error('加载引擎总览失败', e)
  } finally {
    engineLoading.value = false
  }
}

async function loadSchedulerStatus() {
  try {
    const r = await http.get(`${API_PREFIX}/monitor/engine/scheduler`)
    schedulerData.value = r
  } catch (e) {
    console.error('加载定时任务状态失败', e)
  }
}

function startEngineRefresh() {
  if (engineRefreshTimer) return
  engineRefreshTimer = setInterval(() => {
    if (activeTab.value === 'engine') {
      loadEngineOverview()
      loadSchedulerStatus()
    }
  }, 5000)
}

function stopEngineRefresh() {
  if (engineRefreshTimer) {
    clearInterval(engineRefreshTimer)
    engineRefreshTimer = null
  }
}

function modePct(mode) {
  const total = engineData.value?.strategies?.active || 0
  if (total === 0) return 0
  const count = engineData.value.strategies[mode] || 0
  return Math.round((count / total) * 100)
}

function scoreClass(score) {
  if (!score) return 'neutral'
  if (score >= 7) return 'high'
  if (score >= 4) return 'mid'
  return 'low'
}

function orderStatusText(status) {
  const map = {
    0: '待下单', 1: '已提交', 2: '已成交', 3: '部分成交',
    4: '已撤销', 5: '失败', 6: '止盈成交', 7: '止损成交', 8: '风控平仓',
  }
  return map[status] || '未知'
}

function orderStatusType(status) {
  const map = {
    0: 'info', 1: 'warning', 2: 'success', 3: 'warning',
    4: 'info', 5: 'danger', 6: 'success', 7: 'danger', 8: 'danger',
  }
  return map[status] || 'info'
}

function triggerReasonText(reason) {
  const map = {
    1: '手动', 2: '评分触发', 3: '止盈', 4: '止损',
    5: '单笔回撤', 6: '日亏损超限', 7: '连续亏损', 8: '评分反转',
  }
  return map[reason] || '--'
}

function formatNumber(val) {
  if (val === null || val === undefined) return '0.00'
  const num = Number(val)
  if (Math.abs(num) >= 1000000) return (num / 1000000).toFixed(2) + 'M'
  if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2) + 'K'
  return num.toFixed(2)
}

// 监听 tab 切换，进入引擎总览时启动刷新
watch(activeTab, (newTab) => {
  if (newTab === 'engine') {
    loadEngineOverview()
    loadSchedulerStatus()
    startEngineRefresh()
  } else {
    stopEngineRefresh()
  }
})

onMounted(() => { loadStatus(); loadShareTokens(); loadAiTasks(); startAutoRefresh() })
onBeforeUnmount(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
  stopEngineRefresh()
  // 清理所有 SSE 连接
  Object.keys(sseConnections).forEach(tid => closeTaskSse(tid))
})
</script>
<style scoped>
.system-monitor-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-title { margin: 0; font-size: 22px; font-weight: 600; color: #E6EDF3; }
.page-subtitle { font-size: 13px; color: #7A8A9A; margin-top: 4px; }
.header-actions { display: flex; gap: 10px; }

.overview-row { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 16px; margin-bottom: 20px; }

.status-card {
  background: linear-gradient(135deg, #0F1A24 0%, #16232E 100%);
  border-radius: 12px; padding: 24px; display: flex; align-items: center; gap: 20px;
  border: 1px solid #1E3246; position: relative; overflow: hidden;
}
.status-card.status-healthy { border-color: rgba(37, 208, 125, 0.3); }
.status-card.status-warning { border-color: rgba(230, 162, 60, 0.3); }
.status-card.status-critical { border-color: rgba(245, 108, 108, 0.3); }

.status-indicator { position: relative; width: 80px; height: 80px; display: flex; align-items: center; justify-content: center; }
.status-icon {
  width: 64px; height: 64px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(37, 208, 125, 0.15); color: #25D07D; z-index: 2;
}
.status-warning .status-icon { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
.status-critical .status-icon { background: rgba(245, 108, 108, 0.15); color: #f56c6c; }

.pulse-ring {
  position: absolute; width: 80px; height: 80px; border-radius: 50%;
  background: rgba(37, 208, 125, 0.2); animation: pulse 2s ease-out infinite;
}
.status-warning .pulse-ring { background: rgba(230, 162, 60, 0.2); }
.status-critical .pulse-ring { background: rgba(245, 108, 108, 0.2); animation-duration: 1s; }

@keyframes pulse { 0% { transform: scale(0.8); opacity: 1; } 100% { transform: scale(1.4); opacity: 0; } }

.status-info { flex: 1; }
.status-title { font-size: 22px; font-weight: 600; color: #E6EDF3; margin-bottom: 4px; }
.status-desc { font-size: 13px; color: #7A8A9A; margin-bottom: 8px; }
.status-meta { display: flex; gap: 16px; font-size: 12px; color: #5A6A7A; }
.status-issues { display: flex; flex-direction: column; gap: 6px; }

.metric-card { background: #0F1A24; border-radius: 12px; padding: 20px; border: 1px solid #1E3246; }
.metric-item { height: 100%; display: flex; flex-direction: column; justify-content: center; }
.metric-label { font-size: 13px; color: #7A8A9A; margin-bottom: 8px; }
.metric-value { font-size: 28px; font-weight: 700; color: #25D07D; margin-bottom: 10px; font-family: monospace; }
.metric-value.warning { color: #e6a23c; }
.metric-value.critical { color: #f56c6c; }
.metric-sub { font-size: 11px; color: #5A6A7A; margin-top: 6px; }

.monitor-tabs { --el-tabs-header-background: #0F1A24; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.mt-16 { margin-top: 16px; }

.service-list { display: flex; flex-direction: column; gap: 16px; margin-bottom: 20px; }
.service-item {
  display: flex; align-items: center; gap: 14px; padding: 14px;
  background: #0A131B; border-radius: 8px; border: 1px solid #1A2A3A;
}
.svc-icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; }
.db-icon { background: rgba(64, 158, 255, 0.15); color: #409eff; }
.redis-icon { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
.sched-icon { background: rgba(103, 194, 58, 0.15); color: #67c23a; }
.svc-info { flex: 1; }
.svc-name { font-size: 14px; color: #E6EDF3; font-weight: 500; }
.svc-desc { font-size: 12px; color: #7A8A9A; margin-top: 2px; }

.task-list { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid #1A2A3A; }
.task-item { display: flex; align-items: center; gap: 10px; font-size: 13px; padding: 6px 0; }
.task-dot { width: 6px; height: 6px; border-radius: 50%; background: #25D07D; }
.task-name { color: #B0BEC5; flex: 1; }
.task-interval { color: #5A6A7A; font-size: 12px; margin-right: 8px; }

.issue-list { display: flex; flex-direction: column; gap: 10px; }
.issue-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 12px;
  border-radius: 8px; background: #0A131B; border-left: 3px solid #e6a23c;
}
.issue-item.level-critical { border-left-color: #f56c6c; background: rgba(245, 108, 108, 0.08); }
.issue-icon { font-size: 18px; margin-top: 1px; flex-shrink: 0; }
.issue-item.level-warning .issue-icon { color: #e6a23c; }
.issue-item.level-critical .issue-icon { color: #f56c6c; }
.issue-msg { font-size: 13px; color: #E6EDF3; line-height: 1.5; }

.log-stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.log-stat-item { text-align: center; padding: 16px; background: #0A131B; border-radius: 8px; border: 1px solid #1A2A3A; }
.ls-count { font-size: 28px; font-weight: 700; font-family: monospace; margin-bottom: 4px; }
.log-stat-item.info .ls-count { color: #409eff; }
.log-stat-item.warning .ls-count { color: #e6a23c; }
.log-stat-item.error .ls-count { color: #f56c6c; }
.log-stat-item.debug .ls-count { color: #909399; }
.log-stat-item.total .ls-count { color: #25D07D; }
.ls-label { font-size: 12px; color: #7A8A9A; }

.selfcheck-overview {
  display: flex; align-items: center; gap: 24px; padding: 24px;
  border-radius: 10px; margin-bottom: 20px;
  background: linear-gradient(135deg, rgba(37, 208, 125, 0.08) 0%, rgba(37, 208, 125, 0.02) 100%);
  border: 1px solid rgba(37, 208, 125, 0.2);
}
.selfcheck-overview.status-warning {
  background: linear-gradient(135deg, rgba(230, 162, 60, 0.08) 0%, rgba(230, 162, 60, 0.02) 100%);
  border-color: rgba(230, 162, 60, 0.2);
}
.selfcheck-overview.status-critical {
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.08) 0%, rgba(245, 108, 108, 0.02) 100%);
  border-color: rgba(245, 108, 108, 0.2);
}
.sc-score { text-align: center; }
.sc-score-num { font-size: 48px; font-weight: 700; color: #25D07D; font-family: monospace; line-height: 1; }
.status-warning .sc-score-num { color: #e6a23c; }
.status-critical .sc-score-num { color: #f56c6c; }
.sc-score-label { font-size: 12px; color: #7A8A9A; margin-top: 4px; }
.sc-title { font-size: 20px; font-weight: 600; color: #E6EDF3; margin-bottom: 6px; }
.sc-detail { font-size: 13px; color: #B0BEC5; margin-bottom: 4px; }
.sc-time { font-size: 12px; color: #5A6A7A; }

.check-result-list { display: flex; flex-direction: column; gap: 8px; }
.check-result-item {
  display: flex; align-items: center; gap: 12px; padding: 12px 14px;
  background: #0A131B; border-radius: 8px; border: 1px solid #1A2A3A;
}
.check-result-item.fail { border-color: rgba(245, 108, 108, 0.3); background: rgba(245, 108, 108, 0.05); }
.cr-status { flex-shrink: 0; }
.cr-name { font-size: 14px; color: #E6EDF3; min-width: 180px; }
.cr-detail { flex: 1; display: flex; gap: 6px; flex-wrap: wrap; }
.cr-error { color: #f56c6c; font-size: 13px; }

.log-controls { display: flex; gap: 10px; align-items: center; }
.log-viewer { padding: 0 !important; }
.log-content {
  max-height: 500px; overflow-y: auto; padding: 12px;
  background: #070D13; font-family: Consolas, monospace; font-size: 12px; line-height: 1.6;
}
.log-line { display: flex; gap: 8px; padding: 3px 6px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; }
.log-line:hover { background: rgba(255, 255, 255, 0.03); }
.log-time { color: #5A6A7A; flex-shrink: 0; }
.log-level { font-weight: 600; flex-shrink: 0; min-width: 60px; }
.tag-INFO { color: #409eff; }
.tag-WARNING { color: #e6a23c; }
.tag-ERROR { color: #f56c6c; }
.tag-DEBUG { color: #909399; }
.tag-CRITICAL { color: #f56c6c; font-weight: 700; }
.log-module { color: #7A8A9A; flex-shrink: 0; min-width: 200px; }
.log-message { color: #B0BEC5; flex: 1; }
.log-line.level-ERROR { background: rgba(245, 108, 108, 0.06); }
.log-line.level-WARNING { background: rgba(230, 162, 60, 0.04); }
.log-pagination { padding: 12px 16px; display: flex; justify-content: center; border-top: 1px solid #1A2A3A; }

.share-hint {
  display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px;
  background: rgba(64, 158, 255, 0.08); border: 1px solid rgba(64, 158, 255, 0.2);
  border-radius: 8px; color: #B0BEC5; font-size: 13px; margin-bottom: 20px;
}
.share-hint .el-icon { color: #409eff; margin-top: 2px; flex-shrink: 0; }

.share-list { display: flex; flex-direction: column; gap: 10px; }
.share-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; background: #0A131B; border-radius: 8px; border: 1px solid #1A2A3A;
}
.share-token { font-family: monospace; font-size: 14px; color: #E6EDF3; margin-bottom: 4px; }
.share-meta { font-size: 12px; color: #7A8A9A; }
.share-actions { display: flex; gap: 8px; }

.share-create-form { padding: 10px 0; }
.form-item { margin-bottom: 16px; }
.form-item label { display: block; font-size: 13px; color: #B0BEC5; margin-bottom: 8px; }
.form-tip {
  display: flex; align-items: flex-start; gap: 8px; padding: 12px;
  background: rgba(230, 162, 60, 0.08); border-radius: 6px; font-size: 12px; color: #e6a23c;
}
.form-tip .el-icon { flex-shrink: 0; margin-top: 1px; }

.empty-hint { text-align: center; padding: 40px 20px; color: #909399; }

@media (max-width: 1200px) {
  .overview-row { grid-template-columns: 1fr 1fr; }
  .two-col { grid-template-columns: 1fr; }
  .log-stats-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 768px) {
  .overview-row { grid-template-columns: 1fr; }
  .log-stats-row { grid-template-columns: repeat(2, 1fr); }
}

/* AI 控制中心 */
.ai-control-wrap { padding: 4px 0; }
.ai-task-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.ai-task-card {
  background: linear-gradient(135deg, #0F1A24 0%, #16232E 100%);
  border: 1px solid #1E3246;
  border-radius: 12px;
  padding: 22px;
  cursor: pointer;
  transition: all 0.25s ease;
  text-align: center;
}
.ai-task-card:hover {
  border-color: #25D07D;
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(37,208,125,0.15);
}
.ai-task-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  margin: 0 auto 14px;
}
.ai-task-name {
  font-size: 15px;
  font-weight: 600;
  color: #E6EDF3;
  margin-bottom: 8px;
}
.ai-task-desc {
  font-size: 12px;
  color: #7A8A9A;
  line-height: 1.5;
}

.ai-task-list-section { margin-top: 8px; }
.ai-task-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.section-title { font-size: 15px; font-weight: 600; color: #E6EDF3; }
.sse-status {
  font-size: 12px;
  color: #7A8A9A;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7A8A9A;
  display: inline-block;
}
.sse-dot.active {
  background: #25D07D;
  box-shadow: 0 0 6px rgba(37,208,125,0.6);
}

.ai-empty { text-align: center; padding: 30px 0; }

.ai-task-list { display: flex; flex-direction: column; gap: 10px; }
.ai-task-item {
  background: #0A131B;
  border: 1px solid #1A2A3A;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.ai-task-item:hover {
  border-color: #25D07D;
  background: rgba(37,208,125,0.04);
}
.ati-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.ati-name { font-size: 14px; font-weight: 600; color: #E6EDF3; }
.ati-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #7A8A9A;
  margin-bottom: 10px;
}
.ati-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ati-progress :deep(.el-progress) { flex: 1; }
.ati-pct { font-size: 12px; color: #94A3B8; min-width: 36px; text-align: right; }
.ati-error {
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(245,108,108,0.1);
  border-radius: 6px;
  color: #f56c6c;
  font-size: 12px;
}

.task-create-form :deep(.form-item) { margin-bottom: 16px; }
.task-create-form :deep(.form-item label) {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #CBD5E1;
  font-weight: 500;
}

.task-detail-content {
  max-height: 65vh;
  overflow-y: auto;
  color: #CBD5E1;
  font-size: 13px;
}
.task-detail-content table { width: 100%; border-collapse: collapse; }
.task-detail-content th {
  background: #0A131B;
  padding: 8px 10px;
  text-align: left;
  color: #7A8A9A;
  font-weight: 500;
  border-bottom: 1px solid #1A2A3A;
}
.task-detail-content td {
  padding: 8px 10px;
  border-bottom: 1px solid #0F1A24;
}

@media (max-width: 900px) {
  .ai-task-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .ai-task-grid { grid-template-columns: 1fr; }
}

/* ============ 交易引擎总览 ============ */
.engine-overview-wrap { padding: 0; }
.engine-top-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: #0F1A24; border-radius: 8px;
  margin-bottom: 16px; font-size: 13px;
}
.engine-status-badge {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 12px; border-radius: 20px;
  background: rgba(248, 113, 113, 0.15); color: #F87171;
}
.engine-status-badge.running {
  background: rgba(37, 208, 125, 0.15); color: #25D07D;
}
.engine-status-badge .status-dot {
  width: 8px; height: 8px; border-radius: 50%; background: currentColor;
}
.engine-status-badge.running .status-dot {
  animation: pulse-dot 1.5s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.3); }
}
.engine-refresh {
  display: flex; align-items: center; gap: 6px; color: #7A8A9A;
}
.engine-refresh .el-icon { cursor: pointer; }
.engine-update-time { color: #7A8A9A; }

.engine-stat-grid {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 16px;
}
.engine-stat-card {
  background: #0F1A24; border-radius: 10px; padding: 16px;
  display: flex; gap: 12px; align-items: center;
  border: 1px solid #1a2733;
}
.esc-icon {
  width: 44px; height: 44px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; flex-shrink: 0;
}
.esc-info { flex: 1; min-width: 0; }
.esc-value {
  font-size: 24px; font-weight: 700; color: #E6EDF3;
  line-height: 1.2; margin-bottom: 2px;
}
.esc-label { font-size: 12px; color: #7A8A9A; margin-bottom: 2px; }
.esc-sub { font-size: 11px; color: #5A6A7A; }
.esc-sub.profit { color: #25D07D; }
.esc-sub.loss { color: #F87171; }

.engine-two-col {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  margin-bottom: 16px;
}
.engine-col { display: flex; flex-direction: column; gap: 16px; }

.sched-task-list { display: flex; flex-direction: column; gap: 8px; }
.sched-task-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; background: #0A1118; border-radius: 8px;
  border: 1px solid #1a2733;
}
.st-icon { font-size: 20px; }
.st-info { flex: 1; }
.st-name { font-size: 13px; color: #E6EDF3; font-weight: 500; }
.st-interval { font-size: 11px; color: #5A6A7A; margin-top: 2px; }
.st-status { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.st-next-run { font-size: 10px; color: #5A6A7A; white-space: nowrap; }

.strategy-mode-bars { display: flex; flex-direction: column; gap: 14px; }
.smb-item { display: flex; flex-direction: column; gap: 6px; }
.smb-label {
  display: flex; justify-content: space-between;
  font-size: 13px; color: #C8D4E0;
}
.smb-count { font-weight: 600; color: #E6EDF3; }

.position-list { display: flex; flex-direction: column; gap: 8px; }
.pos-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; background: #0A1118; border-radius: 8px;
  border: 1px solid #1a2733;
}
.pos-left { display: flex; align-items: center; gap: 8px; }
.pos-symbol { font-weight: 600; color: #E6EDF3; font-size: 14px; }
.pos-right { text-align: right; }
.pos-pnl {
  display: block; font-weight: 600; font-size: 14px;
}
.pos-pnl.profit { color: #25D07D; }
.pos-pnl.loss { color: #F87171; }
.pos-pct { font-size: 11px; }
.pos-pct.profit { color: #25D07D; }
.pos-pct.loss { color: #F87171; }

.symbol-score-list { display: flex; flex-direction: column; gap: 10px; max-height: 320px; overflow-y: auto; }
.ss-item {
  padding: 10px 12px; background: #0A1118; border-radius: 8px;
  border: 1px solid #1a2733;
}
.ss-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
}
.ss-symbol { font-weight: 600; color: #E6EDF3; font-size: 13px; flex: 1; }
.ss-score {
  font-weight: 700; font-size: 15px;
}
.ss-score.high { color: #25D07D; }
.ss-score.mid { color: #FBBF24; }
.ss-score.low { color: #F87171; }
.ss-score.neutral { color: #7A8A9A; }
.ss-bar {
  height: 4px; background: #1a2733; border-radius: 2px; overflow: hidden;
  margin-bottom: 6px;
}
.ss-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.ss-bar-fill.high { background: linear-gradient(90deg, #25D07D, #4ADE80); }
.ss-bar-fill.mid { background: linear-gradient(90deg, #FBBF24, #F59E0B); }
.ss-bar-fill.low { background: linear-gradient(90deg, #F87171, #EF4444); }
.ss-detail {
  display: flex; gap: 12px; font-size: 11px; color: #7A8A9A;
}
.ss-detail .profit { color: #25D07D; }
.ss-detail .loss { color: #F87171; }

.empty-hint {
  display: flex; flex-direction: column; align-items: center;
  padding: 20px 0; color: #5A6A7A;
}

.rotating { animation: rotating 1s linear infinite; }
@keyframes rotating { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.profit { color: #25D07D; }
.loss { color: #F87171; }

@media (max-width: 1200px) {
  .engine-stat-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 800px) {
  .engine-stat-grid { grid-template-columns: repeat(2, 1fr); }
  .engine-two-col { grid-template-columns: 1fr; }
}
</style>