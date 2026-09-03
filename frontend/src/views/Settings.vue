<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><Setting /></el-icon>系统设置</h2>
        <div class="page-subtitle">全局参数配置：交易所主账号、新闻API、告警推送、通知渠道</div>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="6">
        <div class="side-menu">
          <div class="menu-item" :class="{ 'is-active': active === 'general' }" @click="handleMenuSelect('general')">
            <el-icon><Tools /></el-icon><span>通用参数</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'exchange' }" @click="handleMenuSelect('exchange')">
            <el-icon><Coin /></el-icon><span>交易所主账号</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'demo' }" @click="handleMenuSelect('demo')">
            <el-icon><DataLine /></el-icon><span>演示API配置</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'news' }" @click="handleMenuSelect('news')">
            <el-icon><Reading /></el-icon><span>新闻数据源</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'cryptopanic' }" @click="handleMenuSelect('cryptopanic')">
            <el-icon><Connection /></el-icon><span>实时新闻WS</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'crawler' }" @click="handleMenuSelect('crawler')">
            <el-icon><Monitor /></el-icon><span>爬虫健康检测</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'notify' }" @click="handleMenuSelect('notify')">
            <el-icon><Bell /></el-icon><span>告警推送</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'ai' }" @click="handleMenuSelect('ai')">
            <el-icon><Cpu /></el-icon><span>AI 默认配置</span>
          </div>
          <div class="menu-item" :class="{ 'is-active': active === 'about' }" @click="handleMenuSelect('about')">
            <el-icon><InfoFilled /></el-icon><span>关于系统</span>
          </div>
        </div>
      </el-col>
      <el-col :span="18">
        <!-- 通用 -->
        <div v-show="active==='general'" class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">通用参数</span></div>
          <div class="panel-card__body">
            <el-form label-width="180px">
              <el-form-item label="系统名称"><el-input v-model="g.appName" /></el-form-item>
              <el-form-item label="时区"><el-select v-model="g.tz" style="width:260px;"><el-option label="Asia/Shanghai UTC+8" value="Asia/Shanghai" /></el-select></el-form-item>
              <el-form-item label="允许登录IP白名单"><el-input v-model="g.ip_whitelist" type="textarea" placeholder="每行一个，留空=不限制" :rows="3" /></el-form-item>
              <el-form-item label="会话时长(分钟)"><el-input-number v-model="g.session_min" :min="15" :max="10080" /></el-form-item>
              <el-form-item label="是否启用操作审计"><el-switch v-model="g.audit" /></el-form-item>
              <el-form-item label="单IP最大登录失败次数"><el-input-number v-model="g.max_fail" :min="3" :max="20" /></el-form-item>
              <el-form-item><el-button type="primary" @click="saveGeneral">保存配置</el-button></el-form-item>
            </el-form>
          </div>
        </div>
        <!-- 交易所主账号 -->
        <div v-show="active==='exchange'" class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">交易所主账号（用于创建子账号，安全存储建议加密）</span></div>
          <div class="panel-card__body">
            <el-tabs>
              <el-tab-pane label="币安 Binance" name="bn">
                <el-form label-width="160px">
                  <el-form-item label="API Key"><el-input v-model="e.bn.key" type="password" show-password /></el-form-item>
                  <el-form-item label="API Secret"><el-input v-model="e.bn.secret" type="password" show-password /></el-form-item>
                  <el-form-item label="环境"><el-radio-group v-model="e.bn.testnet"><el-radio-button :value="true">测试网</el-radio-button><el-radio-button :value="false">主网</el-radio-button></el-radio-group></el-form-item>
                  <el-form-item label="API Base URL"><el-input v-model="e.bn.url" /></el-form-item>
                  <el-form-item>
                    <el-button type="primary" @click="testConn('bn')" :loading="testingExchange">测试连接</el-button>
                    <el-button type="success" style="margin-left:10px;" @click="saveExchange" :loading="savingExchange">保存</el-button>
                  </el-form-item>
                </el-form>
              </el-tab-pane>
              <el-tab-pane label="OKX 欧易" name="okx">
                <el-form label-width="160px">
                  <el-form-item label="API Key"><el-input v-model="e.okx.key" type="password" show-password /></el-form-item>
                  <el-form-item label="API Secret"><el-input v-model="e.okx.secret" type="password" show-password /></el-form-item>
                  <el-form-item label="Passphrase"><el-input v-model="e.okx.pass" type="password" show-password /></el-form-item>
                  <el-form-item label="环境"><el-radio-group v-model="e.okx.testnet"><el-radio-button :value="true">模拟盘</el-radio-button><el-radio-button :value="false">实盘</el-radio-button></el-radio-group></el-form-item>
                  <el-form-item label="API Base URL"><el-input v-model="e.okx.url" /></el-form-item>
                  <el-form-item>
                    <el-button type="primary" @click="testConn('okx')" :loading="testingExchange">测试连接</el-button>
                    <el-button type="success" style="margin-left:10px;" @click="saveExchange" :loading="savingExchange">保存</el-button>
                  </el-form-item>
                </el-form>
              </el-tab-pane>
            </el-tabs>
          </div>
        </div>
        <!-- 演示API配置 -->
        <div v-show="active==='demo'" class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">演示API配置（用于无子账号时拉取行情演示）</span>
          </div>
          <div class="panel-card__body">
            <el-alert type="info" :closable="false" style="margin-bottom:16px;">
              配置后，未绑定子账号的用户也能查看K线行情和所有分析功能。用户绑定自己的子账号后，演示API自动失效（优先使用用户自己的子账号）。
            </el-alert>
            <el-form label-width="180px">
              <el-form-item label="启用演示API">
                <el-switch v-model="demo.enabled" active-text="启用" inactive-text="停用" />
              </el-form-item>
              <el-form-item label="交易所">
                <el-radio-group v-model="demo.exchange">
                  <el-radio-button value="binance">币安 Binance</el-radio-button>
                  <el-radio-button value="okx">OKX</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="demo.api_key" placeholder="输入交易所API Key" style="width:420px;" />
              </el-form-item>
              <el-form-item label="API Secret">
                <el-input v-model="demo.api_secret" type="password" show-password
                  :placeholder="demo.api_secret_has_value ? '留空则不修改现有Secret' : '输入API Secret'"
                  style="width:420px;" />
                <div v-if="demo.api_secret_has_value" style="font-size:12px;color:#67C23A;margin-top:4px;">
                  已保存Secret：{{ demo.api_secret_masked }}，留空则不修改
                </div>
              </el-form-item>
              <el-form-item label="环境">
                <el-radio-group v-model="demo.testnet">
                  <el-radio-button :value="true">测试网</el-radio-button>
                  <el-radio-button :value="false">主网</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="自定义Endpoint">
                <el-input v-model="demo.api_endpoint" placeholder="留空使用交易所默认地址" style="width:420px;" />
              </el-form-item>
              <el-form-item>
                <el-button type="success" @click="saveDemo" :loading="savingDemo">保存配置</el-button>
                <el-button style="margin-left:10px;" @click="testDemo" :loading="testingDemo">测试连接</el-button>
              </el-form-item>
            </el-form>
          </div>
        </div>
        <!-- 新闻 -->
        <div v-show="active==='news'" class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">新闻数据源配置</span></div>
          <div class="panel-card__body">
            <el-form label-width="160px">
              <el-form-item label="NewsAPI Key"><el-input v-model="n.newsapi" type="password" show-password /></el-form-item>
              <el-form-item label="CryptoPanic Token"><el-input v-model="n.cryptopanic" type="password" show-password /></el-form-item>
              <el-form-item label="金十数据 API"><el-input v-model="n.jin10" /></el-form-item>
              <el-form-item label="采集频率(分钟)"><el-input-number v-model="n.interval" :min="1" :max="1440" /></el-form-item>
              <el-form-item label="新闻保留天数"><el-input-number v-model="n.retention" :min="7" :max="730" /></el-form-item>
              <el-form-item label="情绪分析语言">
                <el-checkbox-group v-model="n.langs">
                  <el-checkbox value="zh">中文</el-checkbox>
                  <el-checkbox value="en">英文</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
              <el-form-item><el-button type="success" @click="saveNews" :loading="savingNews">保存并重启采集器</el-button></el-form-item>
            </el-form>
          </div>
        </div>
        <!-- CryptoPanic 实时新闻 WebSocket -->
        <div v-show="active==='cryptopanic'" class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#25D07D"><Connection /></el-icon>
              CryptoPanic 实时新闻 WebSocket 配置
            </span>
          </div>
          <div class="panel-card__body">
            <el-alert type="info" :closable="false" style="margin-bottom:16px;">
              配置 CryptoPanic API Token 后，系统通过 WebSocket 实时接收突发新闻（秒级），自动分析情绪和影响级别。
              当高影响新闻方向与持仓相反时，自动触发评分并平仓止损。未配置 Token 或连接断开时，自动回退到 RSS 轮询模式（3分钟间隔）。
            </el-alert>

            <!-- 连接状态 -->
            <div class="cp-status-bar">
              <div class="cp-status-item">
                <span class="status-light" :class="cpWsStatusLightClass"></span>
                <span style="margin-left:8px;font-weight:600;">
                  {{ cpStatusText }}
                </span>
              </div>
              <div class="cp-status-item">
                <el-tag size="small" :type="cp.news_source_mode === 'websocket' ? 'success' : 'warning'" effect="dark">
                  {{ cp.news_source_mode === 'websocket' ? 'WebSocket 实时' : 'RSS 轮询兜底' }}
                </el-tag>
              </div>
              <div class="cp-status-item text-dim" v-if="cp.last_news_at">
                最近新闻: {{ cp.last_news_at }}
              </div>
              <div class="cp-status-item text-dim">
                已接收: {{ cp.news_count || 0 }} 条 | 自动止损: {{ cp.auto_close_count || 0 }} 次
              </div>
            </div>

            <el-form label-width="180px" style="margin-top:20px;">
              <el-form-item label="CryptoPanic API Token">
                <el-input
                  v-model="cp.token"
                  type="password"
                  show-password
                  :placeholder="cp.token_configured ? '已保存Token（' + cp.token_masked + '），留空则不修改' : '输入 CryptoPanic API Token'"
                  style="width:420px;"
                />
                <div style="font-size:12px;color:#909399;margin-top:4px;">
                  免费注册: <a href="https://cryptopanic.com/api/" target="_blank" style="color:#25D07D;">cryptopanic.com/api</a>
                </div>
              </el-form-item>

              <el-form-item label="突发新闻自动止损">
                <el-switch v-model="cp.auto_close" active-text="启用" inactive-text="停用" />
                <div class="text-dim" style="font-size:11px;margin-top:2px;">
                  高影响新闻 + 评分方向与持仓相反 → 自动市价平仓
                </div>
              </el-form-item>

              <el-form-item label="突发新闻自动交易">
                <el-switch v-model="cp.auto_trade" active-text="启用" inactive-text="停用" />
                <div class="text-dim" style="font-size:11px;margin-top:2px;">
                  高影响新闻 + 评分达标 → 自动开新仓
                </div>
              </el-form-item>

              <el-form-item>
                <el-button type="success" @click="saveCryptoPanic" :loading="savingCP">保存配置</el-button>
                <el-button type="primary" @click="testCryptoPanic" :loading="testingCP" style="margin-left:10px;">测试连通</el-button>
                <el-button
                  v-if="cp.wsStatus.running"
                  type="danger"
                  @click="stopCryptoPanicWS"
                  style="margin-left:10px;"
                >停止服务</el-button>
                <el-button
                  v-else
                  type="warning"
                  @click="startCryptoPanicWS"
                  style="margin-left:10px;"
                >启动服务</el-button>
              </el-form-item>
            </el-form>

            <!-- 工作流程说明 -->
            <el-divider content-position="left">突发新闻 → 自动止损 工作流程</el-divider>
            <el-steps :active="4" simple style="margin-top:10px;">
              <el-step title="WebSocket接收" description="秒级推送" />
              <el-step title="AI情绪分析" description="正/负/中性" />
              <el-step title="影响级别≥3" description="高影响新闻" />
              <el-step title="重新评分" description="技术面+新闻+AI" />
              <el-step title="方向相反→平仓" description="市价止损" />
            </el-steps>
          </div>
        </div>
        <!-- 告警 -->
        <div v-show="active==='notify'" class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">告警推送渠道</span></div>
          <div class="panel-card__body">
            <el-form label-width="160px">
              <el-form-item label="钉钉机器人Webhook"><el-input v-model="p.dingtalk" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." /></el-form-item>
              <el-form-item label="飞书机器人Webhook"><el-input v-model="p.feishu" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." /></el-form-item>
              <el-divider content-position="left">邮件 SMTP</el-divider>
              <el-form-item label="SMTP服务器"><el-input v-model="p.smtp_host" placeholder="smtp.qq.com / smtp.gmail.com" /></el-form-item>
              <el-form-item label="SMTP端口">
                <el-input-number v-model="p.smtp_port" :min="1" :max="65535" />
                <el-radio-group v-model="p.smtp_ssl" style="margin-left:20px;">
                  <el-radio-button :value="true">SSL</el-radio-button>
                  <el-radio-button :value="false">TLS</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="SMTP账号"><el-input v-model="p.smtp_user" placeholder="xxx@qq.com" /></el-form-item>
              <el-form-item label="SMTP密码/授权码">
                <el-input v-model="p.smtp_pwd" type="password" show-password :placeholder="p.smtp_pwd_has_value ? '留空则不修改现有密码' : '请输入SMTP密码或授权码'" />
                <div v-if="p.smtp_pwd_has_value" style="font-size:12px;color:#67C23A;margin-top:4px;">已保存密码，留空则不修改</div>
              </el-form-item>
              <el-form-item label="收件人(逗号分隔)"><el-input v-model="p.smtp_to" placeholder="a@example.com,b@example.com" /></el-form-item>
              <el-divider content-position="left">推送事件</el-divider>
              <el-checkbox-group v-model="p.events">
                <el-checkbox value="open">开仓</el-checkbox>
                <el-checkbox value="close">平仓</el-checkbox>
                <el-checkbox value="tp">止盈</el-checkbox>
                <el-checkbox value="sl">止损</el-checkbox>
                <el-checkbox value="risk">风控事件</el-checkbox>
                <el-checkbox value="daily">每日报表</el-checkbox>
              </el-checkbox-group>
              <div style="margin-top:20px;">
                <el-button type="success" @click="saveNotify" :loading="savingNotify">保存配置</el-button>
                <el-button style="margin-left:10px;" @click="testSmtp" :loading="testingSmtp">发送测试邮件</el-button>
              </div>
            </el-form>
          </div>
        </div>
        <!-- AI 多API故障转移配置 -->
        <div v-show="active==='ai'" class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">AI 多API故障转移</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="status-light" :class="poolStatusClass"></span>
              <span :style="{ fontSize: '13px', color: poolStatusColor }">{{ poolStatusText }}</span>
            </div>
          </div>
          <div class="panel-card__body">
            <el-alert type="info" :closable="false" style="margin-bottom:16px;">
              配置多个AI API接口，系统自动按优先级调用。主接口失败时自动切换到备用接口，防止系统卡死。连续失败3次的接口会被自动标记为不可用。
            </el-alert>

            <!-- 操作按钮 -->
            <div style="margin-bottom:16px;display:flex;align-items:center;gap:12px;">
              <el-button type="primary" @click="showAddKey = true">添加API</el-button>
              <el-button type="warning" @click="healthCheckAll" :loading="checkingAll">一键检测全部</el-button>
              <span v-if="lastHealthCheck" style="font-size:13px;color:#909399;">
                上次检测: {{ lastHealthCheck }}
              </span>
              <span v-if="aiKeys.length > 0" style="font-size:13px;color:#909399;margin-left:auto;">
                在线 <b style="color:#25D07D;">{{ activeKeyCount }}</b> / 故障 <b style="color:#EF4444;">{{ failedKeyCount }}</b> / 共 {{ aiKeys.length }} 个
              </span>
            </div>

            <!-- API列表 -->
            <el-table :data="aiKeys" border style="width:100%;" v-loading="loadingKeys">
              <el-table-column label="优先级" width="80" prop="priority">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.priority }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="名称" prop="name" width="120" />
              <el-table-column label="供应商" prop="provider" width="100" />
              <el-table-column label="模型" prop="model_name" width="140" />
              <el-table-column label="API Key" width="160">
                <template #default="{ row }">
                  <span v-if="row.has_key" style="font-size:12px;color:#67C23A;">{{ row.api_key_masked }}</span>
                  <span v-else style="color:#909399;">未设置</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="120">
                <template #default="{ row }">
                  <div style="display:flex;align-items:center;gap:6px;">
                    <span class="status-light" :class="keyStatusClass(row.status)"></span>
                    <span :style="{ fontSize: '12px', color: keyStatusColor(row.status) }">{{ keyStatusText(row.status) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="失败次数" prop="fail_count" width="80" />
              <el-table-column label="上次检测" width="160">
                <template #default="{ row }">
                  <span style="font-size:12px;">{{ row.last_checked || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="testKey(row)" :loading="row._testing">测试</el-button>
                  <el-button size="small" type="primary" @click="editKey(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteKey(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="!loadingKeys && aiKeys.length === 0" style="text-align:center;padding:40px;color:#909399;">
              暂无AI API配置，点击「添加API」创建第一个
            </div>

            <!-- 添加/编辑弹窗 -->
            <el-dialog v-model="showAddKey" :title="editingId ? '编辑API' : '添加API'" width="560px">
              <el-form label-width="120px">
                <el-form-item label="名称">
                  <el-input v-model="newKey.name" placeholder="主用 / 备用1 / 备用2" />
                </el-form-item>
                <el-form-item label="供应商">
                  <el-select v-model="newKey.provider" style="width:100%;">
                    <el-option label="自定义接口(推荐)" value="custom" />
                    <el-option label="OpenAI GPT" value="openai" />
                    <el-option label="Anthropic Claude" value="anthropic" />
                    <el-option label="本地模型(Ollama)" value="local" />
                  </el-select>
                </el-form-item>
                <el-form-item label="模型名称">
                  <el-input v-model="newKey.model_name" placeholder="gpt-4o / deepseek-chat / qwen-plus" />
                </el-form-item>
                <el-form-item label="API Endpoint">
                  <el-input v-model="newKey.api_endpoint" placeholder="https://api.example.com/v1" />
                </el-form-item>
                <el-form-item label="API Key">
                  <el-input v-model="newKey.api_key_plain" type="password" show-password
                    :placeholder="editingId && newKey._has_key ? '留空则不修改' : 'sk-...'" />
                </el-form-item>
                <el-form-item label="优先级">
                  <el-input-number v-model="newKey.priority" :min="1" :max="100" />
                  <span style="margin-left:10px;font-size:12px;color:#909399;">数字越小越优先</span>
                </el-form-item>
                <el-row :gutter="16">
                  <el-col :span="8">
                    <el-form-item label="温度">
                      <el-input-number v-model="newKey.temperature" :min="0" :max="10" style="width:100%;" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="最大Token">
                      <el-input-number v-model="newKey.max_tokens" :min="128" :max="8192" :step="128" style="width:100%;" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="超时(秒)">
                      <el-input-number v-model="newKey.request_timeout_sec" :min="5" :max="120" style="width:100%;" />
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form>
              <template #footer>
                <el-button @click="showAddKey = false">取消</el-button>
                <el-button type="primary" @click="saveKey" :loading="savingKey">保存</el-button>
              </template>
            </el-dialog>
          </div>
        </div>
        <!-- 爬虫健康检测 -->
        <div v-show="active==='crawler'" class="panel-card">
          <div class="panel-card__header">
            <span class="panel-card__title">
              <el-icon style="color:#25D07D"><Monitor /></el-icon>
              爬虫健康检测
            </span>
            <el-button link type="primary" size="small" :loading="crawlerLoading" @click="loadCrawlerHealth">刷新</el-button>
          </div>
          <div class="panel-card__body">
            <!-- 概览统计 -->
            <el-row :gutter="16" style="margin-bottom:16px;" v-if="crawlerSummary">
              <el-col :span="6">
                <div class="crawler-stat-card">
                  <div class="crawler-stat-card__value">{{ crawlerSummary.total }}</div>
                  <div class="crawler-stat-card__label">爬虫总数</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="crawler-stat-card crawler-stat-card--healthy">
                  <div class="crawler-stat-card__value" style="color:#25D07D;">{{ crawlerSummary.healthy }}</div>
                  <div class="crawler-stat-card__label">正常</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="crawler-stat-card crawler-stat-card--warning">
                  <div class="crawler-stat-card__value" style="color:#FBBF24;">{{ crawlerSummary.warning }}</div>
                  <div class="crawler-stat-card__label">异常</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="crawler-stat-card crawler-stat-card--critical">
                  <div class="crawler-stat-card__value" style="color:#F87171;">{{ crawlerSummary.critical }}</div>
                  <div class="crawler-stat-card__label">被屏蔽</div>
                </div>
              </el-col>
            </el-row>

            <!-- 爬虫列表表格 -->
            <el-table :data="crawlerList" border style="width:100%;" v-loading="crawlerLoading">
              <el-table-column label="数据源" prop="source_name" width="140" />
              <el-table-column label="爬虫类" prop="crawler_class" width="200" />
              <el-table-column label="24h采集" width="100" align="center">
                <template #default="{ row }">
                  <span :style="{ color: row.count_24h > 0 ? '#25D07D' : '#F87171', fontWeight: 600 }">{{ row.count_24h }}</span>
                </template>
              </el-table-column>
              <el-table-column label="7天采集" prop="count_7d" width="100" align="center" />
              <el-table-column label="最后采集时间" width="180">
                <template #default="{ row }">
                  <span v-if="row.last_article_at" style="font-size:12px;">{{ formatTime(row.last_article_at) }}</span>
                  <span v-else style="color:#6b7280;font-size:12px;">从未采集</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <div style="display:flex;align-items:center;justify-content:center;gap:6px;">
                    <span class="crawler-dot" :class="row.status"></span>
                    <span :style="{ color: row.status === 'healthy' ? '#25D07D' : row.status === 'warning' ? '#FBBF24' : '#F87171', fontSize: '12px' }">
                      {{ row.status_cn }}
                    </span>
                  </div>
                </template>
              </el-table-column>
            </el-table>

            <!-- 说明 -->
            <el-alert type="info" :closable="false" style="margin-top:16px;">
              <template #title>
                <span style="font-size:13px;">
                  状态判定规则：
                  <span style="color:#25D07D;font-weight:600;">正常</span> = 24小时内有采集 ｜
                  <span style="color:#FBBF24;font-weight:600;">异常</span> = 24小时无采集但7天内有 ｜
                  <span style="color:#F87171;font-weight:600;">被屏蔽</span> = 7天内零采集
                </span>
              </template>
            </el-alert>

            <!-- Xray 节点管理 -->
            <el-divider content-position="left">Xray 节点管理（VLESS/VMess/Trojan/SS → 本地SOCKS5）</el-divider>

            <div class="proxy-pool-bar" v-if="xrayStatus" style="margin-bottom:12px;">
              <div class="proxy-pool-item">
                <span class="status-light" :class="xrayStatus.xray_available ? 'ok' : 'idle'"></span>
                <span style="margin-left:8px;font-weight:600;font-size:13px;">
                  {{ xrayStatus.xray_available ? 'Xray已安装' : 'Xray未安装' }}
                </span>
              </div>
              <div class="proxy-pool-item" v-if="xrayStatus.xray_available">
                <el-tag size="small" type="success" effect="dark">运行 {{ xrayStatus.running || 0 }}</el-tag>
              </div>
              <div class="proxy-pool-item" v-if="xrayStatus.xray_available">
                <el-tag size="small" type="info" effect="dark">总节点 {{ xrayStatus.total_nodes || 0 }}</el-tag>
              </div>
            </div>

            <el-form label-width="120px" style="margin-top:12px;">
              <el-form-item label="订阅URL">
                <el-input
                  v-model="xraySubUrl"
                  placeholder="粘贴订阅链接或单个节点链接 (vless://... vmess://... trojan://...)"
                  style="width:100%;"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="loadXraySubscription" :loading="loadingXraySub">解析节点</el-button>
                <el-button type="success" @click="startXrayAll" :loading="startingXray" style="margin-left:8px;">启动全部</el-button>
                <el-button type="danger" @click="stopXrayAll" :loading="stoppingXray" style="margin-left:8px;">停止全部</el-button>
          <el-button type="warning" @click="checkXrayAll" :loading="checkingXray" style="margin-left:8px;">检测全部</el-button>
          <el-button @click="loadXrayStatus" :loading="loadingXrayStatus" style="margin-left:8px;">刷新状态</el-button>
              </el-form-item>
            </el-form>

            <!-- 解析结果 -->
            <div v-if="xrayParseResult" style="margin-top:8px;padding:8px 12px;background:var(--el-fill-color-light);border-radius:6px;font-size:12px;">
              <span v-if="xrayParseResult.error" style="color:#F87171;">解析失败: {{ xrayParseResult.error }}</span>
              <template v-else>
                <span style="color:#25D07D;font-weight:600;">解析成功: {{ xrayParseResult.parsed }} 个节点</span>
                <div v-if="xrayParseResult.nodes" style="margin-top:4px;">
                  <span v-for="(n, i) in xrayParseResult.nodes" :key="i" style="display:inline-block;margin:2px 6px 0 0;padding:2px 8px;background:var(--el-fill-color);border-radius:4px;font-size:11px;">
                    {{ n.name }} ({{ n.protocol }})
                  </span>
                </div>
              </template>
            </div>

            <!-- Xray 节点列表 -->
            <div v-if="xrayStatus && xrayStatus.nodes && xrayStatus.nodes.length > 0" style="margin-top:12px;">
              <el-table :data="xrayStatus.nodes" border size="small" style="width:100%;">
                <el-table-column label="状态" width="60" align="center">
                  <template #default="{ row }">
                    <div style="display:flex;justify-content:center;">
                      <span class="proxy-status-dot" :class="getXrayStatusClass(row)"></span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="节点名称" prop="name" min-width="180" />
                <el-table-column label="协议" prop="protocol" width="80" align="center" />
                <el-table-column label="本地端口" width="90" align="center">
                  <template #default="{ row }">
                    <span v-if="row.local_port" style="font-size:12px;">{{ row.local_port }}</span>
                    <span v-else style="color:#6b7280;font-size:12px;">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="延迟" width="80" align="center">
                  <template #default="{ row }">
                    <span v-if="row.check_latency_ms" :style="{ color: row.check_latency_ms < 1000 ? '#25D07D' : row.check_latency_ms < 3000 ? '#FBBF24' : '#F87171', fontSize: '12px' }">
                      {{ row.check_latency_ms }}ms
                    </span>
                    <span v-else style="color:#6b7280;font-size:12px;">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="运行状态" width="80" align="center">
                  <template #default="{ row }">
                    <span v-if="row.status === 'running'" style="color:#25D07D;font-size:12px;font-weight:600;">运行中</span>
                    <span v-else-if="row.status === 'stopped'" style="color:#909399;font-size:12px;">已停止</span>
                    <span v-else style="color:#F87171;font-size:12px;">错误</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 代理配置入口 -->
            <el-divider content-position="left">代理配置（反屏蔽 + 订阅自动获取）</el-divider>

            <!-- 代理池实时状态 -->
            <div class="proxy-pool-bar" v-if="proxyPool">
              <div class="proxy-pool-item">
                <span class="status-light" :class="proxyPool.enabled ? 'ok' : 'idle'"></span>
                <span style="margin-left:8px;font-weight:600;font-size:13px;">
                  {{ proxyPool.enabled ? '代理已启用' : '代理未启用' }}
                </span>
              </div>
              <div class="proxy-pool-item">
                <el-tag size="small" type="success" effect="dark">可用 {{ proxyPool.active || 0 }}</el-tag>
              </div>
              <div class="proxy-pool-item">
                <el-tag size="small" type="danger" effect="dark">失效 {{ proxyPool.inactive || 0 }}</el-tag>
              </div>
              <div class="proxy-pool-item">
                <el-tag size="small" type="warning" effect="dark">即将过期 {{ proxyPool.expiring_soon || 0 }}</el-tag>
              </div>
              <div class="proxy-pool-item">
                <el-tag size="small" type="info" effect="dark">总数 {{ proxyPool.total || 0 }}</el-tag>
              </div>
              <div class="proxy-pool-item text-dim" v-if="proxyPool.last_refresh_at" style="font-size:12px;">
                最后刷新: {{ formatTime(proxyPool.last_refresh_at) }}
              </div>
            </div>

            <el-form label-width="160px" style="margin-top:16px;">
              <el-form-item label="启用代理">
                <el-switch v-model="proxy.enabled" active-text="启用" inactive-text="停用" />
                <span class="text-dim" style="font-size:11px;margin-left:8px;">代理失败自动回退直连</span>
              </el-form-item>

              <el-form-item label="订阅URL">
                <el-input
                  v-model="proxy.provider_url"
                  placeholder="http://example.com/proxy/list  或  https://api.proxyprovider.com/v1/list?key=xxx"
                  style="width:100%;"
                />
                <div class="text-dim" style="font-size:11px;margin-top:4px;">
                  填入订阅地址后，系统每 {{ proxy.refresh_minutes }} 分钟自动拉取最新代理节点。
                  支持格式：纯文本、JSON数组、Base64编码（V2Ray/SS订阅）、Clash YAML配置。
                </div>
                <el-button size="small" type="info" @click="testFetchSubscription" :loading="testingFetch" style="margin-top:6px;">
                  测试拉取（预览节点）
                </el-button>
                <div v-if="fetchResult" style="margin-top:8px;padding:8px 12px;background:var(--el-fill-color-light);border-radius:6px;font-size:12px;">
                  <span v-if="fetchResult.error" style="color:#F87171;">拉取失败: {{ fetchResult.error }}</span>
                  <template v-else>
                    <span style="color:#25D07D;font-weight:600;">拉取成功: {{ fetchResult.fetched_count }} 个节点</span>
                    <span v-if="fetchResult.decoded" style="color:#A78BFA;margin-left:8px;">Base64解码</span>
                    <div style="color:#909399;margin-top:4px;">Content-Type: {{ fetchResult.content_type }}</div>
                    <div v-if="fetchResult.proxies && fetchResult.proxies.length" style="margin-top:4px;">
                      <span v-for="(p, i) in fetchResult.proxies" :key="i" style="display:inline-block;margin:2px 6px 0 0;padding:2px 8px;background:var(--el-fill-color);border-radius:4px;font-size:11px;">{{ p }}</span>
                    </div>
                  </template>
                </div>
              </el-form-item>

              <el-form-item label="刷新间隔(分钟)">
                <el-input-number v-model="proxy.refresh_minutes" :min="5" :max="120" />
                <span class="text-dim" style="font-size:11px;margin-left:8px;">订阅URL自动拉取间隔</span>
              </el-form-item>

              <el-form-item label="静态代理列表">
                <el-input
                  v-model="proxy.http_list"
                  type="textarea"
                  :rows="3"
                  placeholder="每行一个，逗号或换行分隔&#10;http://ip:port&#10;http://user:pass@ip:port&#10;socks5://ip:port&#10;socks5://user:pass@ip:port"
                />
                <div class="text-dim" style="font-size:11px;margin-top:4px;">
                  支持协议：<b>http://</b> <b>https://</b> <b>socks5://</b> <b>socks4://</b>
                  <span style="margin-left:8px;">不支持 ss:// vmess:// trojan://（需本地客户端转换）</span>
                </div>
              </el-form-item>

              <el-form-item label="代理TTL(分钟)">
                <el-input-number v-model="proxy.ttl" :min="5" :max="120" />
                <span class="text-dim" style="font-size:11px;margin-left:8px;">代理有效期，到期自动切换</span>
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="saveProxy" :loading="savingProxy">保存并热重载</el-button>
                <el-button type="warning" @click="refreshProxies" :loading="refreshingProxy" style="margin-left:10px;">立即拉取节点</el-button>
                <el-button type="success" @click="checkAllProxies" :loading="checkingProxies" style="margin-left:10px;">检测全部节点</el-button>
                <el-button @click="loadProxyHealth" :loading="loadingProxyHealth" style="margin-left:10px;">刷新状态</el-button>
              </el-form-item>
            </el-form>

            <!-- 代理节点状态列表（绿灯/红灯） -->
            <div v-if="proxyPool && proxyPool.all_proxies_detail && proxyPool.all_proxies_detail.length > 0" style="margin-top:12px;">
              <el-divider content-position="left">代理节点实时状态</el-divider>
              <el-table :data="proxyPool.all_proxies_detail" border size="small" style="width:100%;">
                <el-table-column label="状态" width="60" align="center">
                  <template #default="{ row }">
                    <div style="display:flex;justify-content:center;">
                      <span class="proxy-status-dot" :class="getProxyStatusClass(row)"></span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="代理地址" prop="url" min-width="200" />
                <el-table-column label="延迟" width="100" align="center">
                  <template #default="{ row }">
                    <span v-if="row.check_latency_ms" :style="{ color: row.check_latency_ms < 1000 ? '#25D07D' : row.check_latency_ms < 3000 ? '#FBBF24' : '#F87171', fontSize: '12px' }">
                      {{ row.check_latency_ms }}ms
                    </span>
                    <span v-else style="color:#6b7280;font-size:12px;">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="使用次数" prop="used_count" width="80" align="center" />
                <el-table-column label="连续错误" prop="errors" width="80" align="center" />
                <el-table-column label="最后检测" width="160">
                  <template #default="{ row }">
                    <span v-if="row.last_check_at" style="font-size:12px;">{{ formatTime(row.last_check_at) }}</span>
                    <span v-else style="color:#6b7280;font-size:12px;">未检测</span>
                  </template>
                </el-table-column>
                <el-table-column label="检测结果" width="100" align="center">
                  <template #default="{ row }">
                    <span v-if="row.last_check_ok === true" style="color:#25D07D;font-size:12px;font-weight:600;">正常</span>
                    <span v-else-if="row.last_check_ok === false" style="color:#F87171;font-size:12px;font-weight:600;">失败</span>
                    <span v-else style="color:#6b7280;font-size:12px;">未检测</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
        <!-- 关于 -->
        <div v-show="active==='about'" class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">关于系统</span></div>
          <div class="panel-card__body">
            <el-descriptions :column="1" border size="default">
              <el-descriptions-item label="系统名称">策略交易系统 Trading Strategy Platform</el-descriptions-item>
              <el-descriptions-item label="版本号">v1.0.0</el-descriptions-item>
              <el-descriptions-item label="技术栈">FastAPI + Vue 3 + Element Plus + ECharts + SQLAlchemy</el-descriptions-item>
              <el-descriptions-item label="支持交易所">币安 Binance / 欧易 OKX（子账号模式）</el-descriptions-item>
              <el-descriptions-item label="内置品种">BTC / ETH / SOL / XAU 黄金 / WTI 原油 等USDT合约</el-descriptions-item>
              <el-descriptions-item label="交易周期">1分 / 5分 / 15分 / 1小时 / 4小时 / 日 / 周 / 月</el-descriptions-item>
              <el-descriptions-item label="综合评分体系">技术指标40% + 新闻情绪30% + AI分析30%</el-descriptions-item>
              <el-descriptions-item label="策略类型">标准5指标策略 / EMV趋势跟踪策略</el-descriptions-item>
              <el-descriptions-item label="杠杆范围">1x ~ 125x 可配置（取决于交易所）</el-descriptions-item>
            </el-descriptions>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting, Tools, Coin, Reading, Bell, Cpu, InfoFilled, DataLine, Connection, Monitor } from '@element-plus/icons-vue'
import { http, API_PREFIX } from '@/utils/request'

const active = ref('general')

const handleMenuSelect = (index) => {
  active.value = index
}

// 通用参数
const g = reactive({
  appName: '策略交易系统',
  tz: 'Asia/Shanghai',
  ip_whitelist: '',
  session_min: 1440,
  audit: true,
  max_fail: 5,
})

// 交易所
const e = reactive({
  bn:  { key: '', secret: '', testnet: true, url: 'https://testnet.binancefuture.com' },
  okx: { key: '', secret: '', pass: '', testnet: true, url: 'https://www.okx.com' },
})
const testingExchange = ref(false)
const savingExchange = ref(false)

// 新闻
const n = reactive({
  newsapi: '', cryptopanic: '', jin10: '',
  interval: 10, retention: 180, langs: ['zh', 'en'],
})
const savingNews = ref(false)

// 演示API
const demo = reactive({
  enabled: false,
  exchange: 'binance',
  api_key: '',
  api_secret: '',
  api_secret_has_value: false,
  api_secret_masked: '',
  testnet: true,
  api_endpoint: '',
})
const savingDemo = ref(false)
const testingDemo = ref(false)

// 告警推送
const p = reactive({
  dingtalk: '', feishu: '',
  smtp_host: '', smtp_port: 465, smtp_user: '', smtp_pwd: '', smtp_to: '',
  smtp_ssl: true,
  smtp_pwd_has_value: false,
  events: ['tp', 'sl', 'risk', 'daily'],
})
const savingNotify = ref(false)
const testingSmtp = ref(false)

const savingAi = ref(false)
const testingAi = ref(false)

// AI多API故障转移
const aiKeys = ref([])
const loadingKeys = ref(false)
const showAddKey = ref(false)
const editingId = ref(null)
const savingKey = ref(false)
const checkingAll = ref(false)
const lastHealthCheck = ref('')

// 接口池状态 computed
const activeKeyCount = computed(() => aiKeys.value.filter(k => k.status === 'active').length)
const failedKeyCount = computed(() => aiKeys.value.filter(k => k.status === 'failed').length)
const poolStatusClass = computed(() => {
  if (aiKeys.value.length === 0) return 'idle'
  if (activeKeyCount.value > 0) return 'ok'
  return 'error'
})
const poolStatusText = computed(() => {
  if (aiKeys.value.length === 0) return '未配置接口'
  if (activeKeyCount.value > 0) return `接口池正常 (${activeKeyCount.value}个可用)`
  return '接口池异常 (无可用)'
})
const poolStatusColor = computed(() => {
  if (aiKeys.value.length === 0) return '#909399'
  if (activeKeyCount.value > 0) return '#25D07D'
  return '#EF4444'
})
const keyStatusClass = (status) => {
  if (status === 'active') return 'connected'
  if (status === 'failed') return 'error'
  return 'disconnected'
}
const keyStatusText = (status) => {
  if (status === 'active') return '在线'
  if (status === 'failed') return '故障'
  return '已禁用'
}
const keyStatusColor = (status) => {
  if (status === 'active') return '#25D07D'
  if (status === 'failed') return '#EF4444'
  return '#909399'
}

const newKey = reactive({
  name: '',
  provider: 'custom',
  model_name: 'gpt-4o',
  api_endpoint: '',
  api_key_plain: '',
  priority: 10,
  temperature: 3,
  max_tokens: 800,
  request_timeout_sec: 30,
  max_retries: 2,
  _has_key: false,
})

const providerNameMap = {
  openai: 'OpenAI GPT',
  anthropic: 'Anthropic Claude',
  custom: '自定义接口',
  local: '本地模型 Ollama',
}

// 加载告警配置
const loadNotify = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/settings/notify`)
    p.dingtalk = data.dingtalk || ''
    p.feishu = data.feishu || ''
    p.smtp_host = data.smtp_host || ''
    p.smtp_port = data.smtp_port || 465
    p.smtp_user = data.smtp_user || ''
    p.smtp_pwd = ''  // 密码永远不返回明文
    p.smtp_pwd_has_value = !!(data.smtp_pwd?.has_value)
    p.smtp_to = data.smtp_to || ''
    p.smtp_ssl = data.smtp_ssl !== false
    p.events = Array.isArray(data.events) ? data.events : ['tp', 'sl', 'risk', 'daily']
  } catch (e) {
    // 表还没创建时忽略
  }
}

// 保存告警配置
const saveNotify = async () => {
  if (!p.smtp_host && p.smtp_user) {
    ElMessage.warning('请填写SMTP服务器地址')
    return
  }
  savingNotify.value = true
  try {
    await http.put(`${API_PREFIX}/settings/notify`, {
      dingtalk: p.dingtalk,
      feishu: p.feishu,
      smtp_host: p.smtp_host,
      smtp_port: p.smtp_port,
      smtp_user: p.smtp_user,
      smtp_pwd: p.smtp_pwd,
      smtp_to: p.smtp_to,
      smtp_ssl: p.smtp_ssl,
      events: p.events,
    })
    ElMessage.success('告警配置已保存')
    await loadNotify()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingNotify.value = false
  }
}

// 测试SMTP
const testSmtp = async () => {
  if (!p.smtp_host) {
    ElMessage.warning('请填写SMTP服务器地址')
    return
  }
  if (!p.smtp_user) {
    ElMessage.warning('请填写SMTP账号')
    return
  }
  if (!p.smtp_to) {
    ElMessage.warning('请填写收件人邮箱')
    return
  }
  // 如果密码为空但有已保存的密码，发送一个标记让后端用已保存的
  const pwdToSend = p.smtp_pwd || (p.smtp_pwd_has_value ? '__USE_EXISTING__' : '')
  if (!pwdToSend) {
    ElMessage.warning('请输入SMTP密码/授权码')
    return
  }
  testingSmtp.value = true
  try {
    await http.post(`${API_PREFIX}/settings/notify/test-smtp`, {
      smtp_host: p.smtp_host,
      smtp_port: p.smtp_port,
      smtp_user: p.smtp_user,
      smtp_pwd: pwdToSend,
      smtp_to: p.smtp_to,
      smtp_ssl: p.smtp_ssl,
    })
    ElMessage.success('测试邮件发送成功，请查收收件箱（可能在垃圾邮件中）')
  } catch (e) {
    // 拦截器已展示后端返回的错误消息，这里无需重复弹窗
  } finally {
    testingSmtp.value = false
  }
}

// AI多API：加载列表
const loadAiKeys = async () => {
  loadingKeys.value = true
  try {
    const data = await http.get(`${API_PREFIX}/settings/ai-keys`)
    aiKeys.value = (data.items || []).map(k => ({ ...k, _testing: false }))
  } catch (e) {
    // 表不存在时忽略
  } finally {
    loadingKeys.value = false
  }
}

// AI多API：添加/编辑保存
const saveKey = async () => {
  if (!newKey.name?.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (!editingId.value && !newKey.api_key_plain) {
    ElMessage.warning('请输入API Key')
    return
  }
  savingKey.value = true
  try {
    if (editingId.value) {
      await http.put(`${API_PREFIX}/settings/ai-keys/${editingId.value}`, {
        name: newKey.name,
        provider: newKey.provider,
        model_name: newKey.model_name,
        api_endpoint: newKey.api_endpoint,
        api_key_plain: newKey.api_key_plain || '',
        priority: newKey.priority,
        temperature: newKey.temperature,
        max_tokens: newKey.max_tokens,
        request_timeout_sec: newKey.request_timeout_sec,
        max_retries: newKey.max_retries,
      })
      ElMessage.success('更新成功')
    } else {
      await http.post(`${API_PREFIX}/settings/ai-keys`, {
        name: newKey.name,
        provider: newKey.provider,
        model_name: newKey.model_name,
        api_endpoint: newKey.api_endpoint,
        api_key_plain: newKey.api_key_plain,
        priority: newKey.priority,
        temperature: newKey.temperature,
        max_tokens: newKey.max_tokens,
        request_timeout_sec: newKey.request_timeout_sec,
        max_retries: newKey.max_retries,
      })
      ElMessage.success('添加成功')
    }
    showAddKey.value = false
    editingId.value = null
    await loadAiKeys()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingKey.value = false
  }
}

// AI多API：编辑
const editKey = (row) => {
  editingId.value = row.id
  newKey.name = row.name
  newKey.provider = row.provider
  newKey.model_name = row.model_name
  newKey.api_endpoint = row.api_endpoint || ''
  newKey.api_key_plain = ''
  newKey._has_key = row.has_key
  newKey.priority = row.priority
  newKey.temperature = row.temperature ?? 3
  newKey.max_tokens = row.max_tokens ?? 800
  newKey.request_timeout_sec = row.request_timeout_sec ?? 30
  newKey.max_retries = row.max_retries ?? 2
  showAddKey.value = true
}

// AI多API：测试单个
const testKey = async (row) => {
  row._testing = true
  try {
    const r = await http.post(`${API_PREFIX}/settings/ai-keys/${row.id}/test`)
    if (r && r.success === false) {
      ElMessage.error(r.error || '连接失败')
    } else {
      ElMessage.success(`连接成功！延迟 ${r.latency_ms || '?'}ms`)
    }
    await loadAiKeys()
  } catch (e) {
    ElMessage.error(e?.message || '测试失败')
    await loadAiKeys()
  } finally {
    row._testing = false
  }
}

// AI多API：删除
const deleteKey = async (row) => {
  try {
    await http.delete(`${API_PREFIX}/settings/ai-keys/${row.id}`)
    ElMessage.success('删除成功')
    await loadAiKeys()
  } catch (e) {
    ElMessage.error(e?.message || '删除失败')
  }
}

// AI多API：一键健康检测
const healthCheckAll = async () => {
  checkingAll.value = true
  try {
    const r = await http.post(`${API_PREFIX}/settings/ai-keys/health-check`)
    ElMessage.success(`检测完成: ${r.active}/${r.total} 可用`)
    lastHealthCheck.value = new Date().toLocaleTimeString()
    await loadAiKeys()
  } catch (e) {
    ElMessage.error(e?.message || '检测失败')
    await loadAiKeys()
  } finally {
    checkingAll.value = false
  }
}

// 兼容旧调用
const loadAIConfig = async () => { await loadAiKeys() }
const saveAiConfig = async () => { await loadAiKeys() }
const testAiConn = async () => { await healthCheckAll() }

// CryptoPanic WebSocket 配置
const cp = reactive({
  token: '',
  token_configured: false,
  token_masked: '',
  auto_close: true,
  auto_trade: true,
  wsStatus: { status: 'disconnected' },
  news_source_mode: 'rss_fallback',
  last_news_at: '',
  news_count: 0,
  auto_close_count: 0,
})
const savingCP = ref(false)
const testingCP = ref(false)

const cpStatusText = computed(() => {
  const s = cp.wsStatus.status || 'disconnected'
  const map = {
    connected: 'WebSocket 已连接',
    connecting: '正在连接...',
    error: '连接异常',
    fallback: 'RSS 轮询兜底中',
    disconnected: '未连接',
  }
  return map[s] || s
})
const cpWsStatusLightClass = computed(() => {
  const s = cp.wsStatus.status || 'disconnected'
  const map = {
    connected: 'ok',
    connecting: 'warn',
    error: 'error',
    fallback: 'warn',
    disconnected: 'idle',
  }
  return map[s] || 'idle'
})

const loadCryptoPanic = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/cryptopanic/config`)
    cp.token_configured = data.token_configured || false
    cp.token_masked = data.token_masked || ''
    cp.auto_close = data.auto_close !== false
    cp.auto_trade = data.auto_trade !== false
    cp.wsStatus = data.ws_status || { status: 'disconnected' }
    cp.news_source_mode = data.news_source_mode || 'rss_fallback'
    cp.last_news_at = data.ws_status?.last_news_at || ''
    cp.news_count = data.ws_status?.news_count || 0
    cp.auto_close_count = data.ws_status?.auto_close_count || 0
  } catch (e) {
    // 接口不存在时忽略
  }
}

const saveCryptoPanic = async () => {
  savingCP.value = true
  try {
    const tokenToSend = cp.token || (cp.token_configured ? '__USE_EXISTING__' : '')
    if (!tokenToSend && !cp.token_configured) {
      ElMessage.warning('请输入 CryptoPanic API Token')
      return
    }
    const data = await http.put(`${API_PREFIX}/cryptopanic/config`, {
      token: tokenToSend,
      auto_close: cp.auto_close,
      auto_trade: cp.auto_trade,
    })
    ElMessage.success(data.message || '配置已保存')
    cp.token = ''
    await loadCryptoPanic()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingCP.value = false
  }
}

const testCryptoPanic = async () => {
  if (!cp.token) {
    ElMessage.warning('请先输入 CryptoPanic Token')
    return
  }
  testingCP.value = true
  try {
    const data = await http.post(`${API_PREFIX}/cryptopanic/test`, {
      token: cp.token,
      auto_close: cp.auto_close,
      auto_trade: cp.auto_trade,
    })
    ElMessage.success(data.message || '连接测试成功')
  } catch (e) {
    ElMessage.error(e?.message || '连接测试失败')
  } finally {
    testingCP.value = false
  }
}

const startCryptoPanicWS = async () => {
  try {
    const data = await http.post(`${API_PREFIX}/cryptopanic/start`)
    ElMessage.success(data.message || '服务已启动')
    await loadCryptoPanic()
  } catch (e) {
    ElMessage.error(e?.message || '启动失败')
  }
}

const stopCryptoPanicWS = async () => {
  try {
    const data = await http.post(`${API_PREFIX}/cryptopanic/stop`)
    ElMessage.success(data.message || '服务已停止')
    await loadCryptoPanic()
  } catch (e) {
    ElMessage.error(e?.message || '停止失败')
  }
}

// 演示API：加载
const loadDemo = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/settings/demo-api`)
    demo.enabled = data.enabled || false
    demo.exchange = data.exchange || 'binance'
    demo.api_key = data.api_key || ''
    demo.api_secret = ''
    demo.api_secret_has_value = data.api_secret_has_value || false
    demo.api_secret_masked = data.api_secret_masked || ''
    demo.testnet = data.testnet !== false
    demo.api_endpoint = data.api_endpoint || ''
  } catch {}
}

// 演示API：保存
const saveDemo = async () => {
  if (demo.enabled && !demo.api_key) {
    ElMessage.warning('请输入API Key')
    return
  }
  savingDemo.value = true
  try {
    await http.put(`${API_PREFIX}/settings/demo-api`, {
      enabled: demo.enabled,
      exchange: demo.exchange,
      api_key: demo.api_key,
      api_secret: demo.api_secret,
      testnet: demo.testnet,
      api_endpoint: demo.api_endpoint,
    })
    ElMessage.success('演示API配置已保存')
    await loadDemo()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingDemo.value = false
  }
}

// 演示API：测试连接
const testDemo = async () => {
  if (!demo.api_key) {
    ElMessage.warning('请输入API Key')
    return
  }
  const secretToSend = demo.api_secret || (demo.api_secret_has_value ? '__USE_EXISTING__' : '')
  if (!secretToSend) {
    ElMessage.warning('请输入API Secret')
    return
  }
  testingDemo.value = true
  try {
    const r = await http.post(`${API_PREFIX}/settings/demo-api/test`, {
      exchange: demo.exchange,
      api_key: demo.api_key,
      api_secret: secretToSend,
      testnet: demo.testnet,
    })
    ElMessage.success(`连接成功！BTC 最新价: ${r.last_price}`)
  } catch (e) {
    ElMessage.error(e?.message || '连接测试失败')
  } finally {
    testingDemo.value = false
  }
}

// 其他保存函数（暂未接入后端，先给提示）
const saveGeneral = () => ElMessage.info('通用参数保存功能开发中')
const saveExchange = () => ElMessage.info('交易所主账号保存功能开发中')
const saveNews = () => ElMessage.info('新闻数据源保存功能开发中')
const testConn = (t) => ElMessage.info(`测试${t==='bn'?'币安':'OKX'}连接功能开发中`)

// 爬虫健康检测
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
  if (!iso) return '—'
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

const loadProxyConfig = async () => {
  try {
    const data = await http.get(`${API_PREFIX}/settings/proxy`)
    proxy.enabled = data.enabled || false
    proxy.http_list = data.http_list || ''
    proxy.provider_url = data.provider_url || ''
    proxy.refresh_minutes = data.refresh_minutes || 20
    proxy.ttl = data.ttl || 25
  } catch (e) {
    // 接口不存在时忽略
  }
}

const loadingProxyHealth = ref(false)

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

const getProxyStatusClass = (row) => {
  if (row.last_check_ok === true) return 'proxy-ok'
  if (row.last_check_ok === false) return 'proxy-fail'
  if (row.is_active) return 'proxy-unknown'
  return 'proxy-dead'
}

const testingFetch = ref(false)
const fetchResult = ref(null)

const testFetchSubscription = async () => {
  if (!proxy.provider_url) {
    ElMessage.warning('请先填写订阅URL')
    return
  }
  testingFetch.value = true
  fetchResult.value = null
  try {
    const data = await http.post(`${API_PREFIX}/settings/proxy/test-fetch`, { url: proxy.provider_url })
    fetchResult.value = data
    if (data.error) {
      ElMessage.error(`拉取失败: ${data.error}`)
    } else {
      ElMessage.success(`拉取成功: ${data.fetched_count} 个节点`)
    }
  } catch (e) {
    fetchResult.value = { error: e?.message || '请求失败' }
    ElMessage.error('拉取失败')
  } finally {
    testingFetch.value = false
  }
}

// Xray 节点管理
const xraySubUrl = ref('')
const xrayStatus = ref(null)
const xrayParseResult = ref(null)
const loadingXraySub = ref(false)
const startingXray = ref(false)
const checkingXray = ref(false)

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

const loadingXrayStatus = ref(false)

const loadXrayStatus = async (silent = false) => {
  loadingXrayStatus.value = true
  try {
    const data = await http.get(`${API_PREFIX}/settings/xray/status`)
    xrayStatus.value = data
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

const stoppingXray = ref(false)

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

const getXrayStatusClass = (row) => {
  if (row.last_check_ok === true) return 'proxy-ok'
  if (row.last_check_ok === false) return 'proxy-fail'
  if (row.status === 'running') return 'proxy-unknown'
  return 'proxy-dead'
}

onMounted(() => {
  loadNotify()
  loadAIConfig()
  loadDemo()
  loadCryptoPanic()
  loadCrawlerHealth(true)
  loadProxyConfig()
  loadProxyHealth(true)
  loadXrayStatus(true)
})
</script>

<style lang="scss" scoped>
.side-menu {
  background: #152330;
  border: 1px solid #1E2E41;
  border-radius: 12px;
  padding: 8px 0;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 50px;
  line-height: 50px;
  margin: 4px 10px;
  padding: 0 16px;
  border-radius: 8px;
  cursor: pointer;
  color: #8FA3B8;
  transition: all 0.2s;
  user-select: none;
  &:hover {
    background: #1A2B3D;
    color: #C0D0E0;
  }
  &.is-active {
    background: linear-gradient(90deg, #1A382A, #152330);
    color: #FFFFFF;
    border-left: 3px solid #25D07D;
  }
  .el-icon {
    font-size: 18px;
  }
}
.cp-status-bar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
}
.cp-status-item {
  display: flex;
  align-items: center;
  font-size: 13px;
}
.crawler-stat-card {
  text-align: center;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
  &__value {
    font-size: 28px;
    font-weight: 700;
    line-height: 1.2;
  }
  &__label {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
  }
}
.crawler-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  &.healthy {
    background: #25D07D;
    box-shadow: 0 0 4px #25D07D;
    animation: cp-blink 2s infinite;
  }
  &.warning {
    background: #FBBF24;
    animation: cp-blink 0.5s infinite;
  }
  &.critical {
    background: #F87171;
    animation: cp-pulse 1s infinite;
  }
}
.proxy-pool-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
  flex-wrap: wrap;
}
.proxy-pool-item {
  display: flex;
  align-items: center;
  font-size: 13px;
}
.proxy-status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
  &.proxy-ok {
    background: #25D07D;
    box-shadow: 0 0 6px #25D07D;
    animation: cp-blink 2s infinite;
  }
  &.proxy-fail {
    background: #F87171;
    animation: cp-pulse 1s infinite;
  }
  &.proxy-unknown {
    background: #FBBF24;
    animation: cp-blink 0.5s infinite;
  }
  &.proxy-dead {
    background: #6b7280;
  }
}
</style>
