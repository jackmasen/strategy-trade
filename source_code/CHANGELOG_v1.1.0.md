# 策略交易系统 v1.1.0 变更摘要

> 生成时间：2026-08-30
> 涉及文件：16 项问题修复，覆盖后端核心逻辑、部署配置、安全模块、前端展示

---

## 一、P0 级修复（严重 / 已完成）

### P0-1 平仓巡检接入 APScheduler 兜底
- **文件**：`main.py`
- **问题**：`CELERY_ENABLED=False` 时无进程执行平仓风控巡检，持仓 TP/SL/单笔回撤/日亏无法自动触发平仓
- **修复**：在 `main.py` APScheduler 中注册 30 秒间隔的 `_scheduled_risk_monitor`，复用 `tasks/scheduled.py` 的 `risk_monitor()` 函数，保证不依赖 Celery 即可闭环

### P0-2 冷却期死锁自动恢复
- **文件**：`backend/strategy/engine.py`
- **问题**：连续亏损后冷却期无时间窗口计算逻辑，策略永久锁定无法恢复
- **修复**：基于最后一笔亏损交易的平仓时间 + `cooldown_hours` 计算冷却窗口，到期后自动放行

### P0-3 单笔回撤风控（无需修复）
- **文件**：`backend/tasks/scheduled.py`
- **状态**：`max_single_drawdown` 检查已在 `risk_monitor` 中实现，确认无需改动

### P0-4 默认密码安全告警
- **文件**：`main.py`
- **问题**：使用默认密码 `please_change_me` 启动时无任何告警
- **修复**：启动时检测 `APP_SECRET_KEY` 为默认值则输出 `ERROR` 级别日志告警

### P0-5 CORS 生产环境收紧
- **文件**：`main.py`、`backend/config.py`
- **问题**：CORS 硬编码 `*`，生产环境存在安全风险
- **修复**：新增 `CORS_ALLOW_ORIGINS` 配置项，从 `.env` 读取；当值为 `*` 时自动禁用 `allow_credentials`

---

## 二、P1 级修复（重要 / 已完成）

### P1-6 EMV 策略第10层（滚动胜率观察期）补回实盘
- **文件**：`backend/strategy/emv_strategy.py`、`backend/strategy/scoring.py`、`frontend/src/views/Strategy.vue`
- **问题**：EMV V7 策略 10 层过滤机制中第10层"滚动历史胜率观察期"缺失
- **修复**：
  - 后端 `emv_strategy.py`：`DEFAULT_PARAMS` 新增 `win_rate_min_trades`/`win_rate_min`/`win_rate_lookback`，`generate()` 方法新增第10层检查逻辑
  - `scoring.py`：`StrategyScoringEngine.compute()` 查询滚动历史平仓记录计算胜率并传入 EMV 生成器
  - 前端 `Strategy.vue`：`EMV_LAYERS` 数组补充第10层卡片定义

### P1-7 回测引擎支持 EMV V7 策略
- **文件**：`backend/services/backtest_engine.py`
- **问题**：回测引擎仅支持 MA 金叉死叉策略，无法回测 EMV V7
- **修复**：新增 `_run_emv_strategy()` 函数，逐根 K 线切片调用 `EMVSignalGenerator`，`signal==1` 做多，TP/SL 平仓，复用与实盘一致的信号生成器

### P1-8 调度器去重（CELERY_ENABLED 开关）
- **文件**：`backend/config.py`、`main.py`
- **问题**：APScheduler 与 Celery Beat 同时调度相同任务，导致重复触发
- **修复**：新增 `CELERY_ENABLED` 配置项（默认 `False`）。`False` 时 APScheduler 兜底执行全部定时任务；`True` 时 APScheduler 跳过与 Celery 重叠的任务

### P1-9 新闻 AI 策略两套评分路径统一
- **文件**：`backend/services/news_strategy.py`
- **问题**：`calc_news_sentiment_score()`（独立关键词匹配 + 手动评分）与 `NewsSentimentScorer`（综合评分引擎使用）两套独立路径，分值不一致
- **修复**：重构 `calc_news_sentiment_score()` 内部委托 `NewsSentimentScorer` 评分，再将 `NewsScoreResult`（0-10）转换为兼容的 0-100 dict 格式，消除分值不一致

---

## 三、P2 级修复（优化 / 已完成）

### P2-10 版本号统一 v1.1.0
- **文件**：`main.py`（2 处）、`backend/services/system_manager.py`、`frontend/package.json`
- **问题**：多处版本号仍为 `1.0.0`，与目录名 `v1.1.0` 不一致
- **修复**：全部统一为 `1.1.0`（FastAPI app version、安装标记 version、系统信息 version、前端 package.json version）

### P2-11 system_manager.py 数据库路径动态读取
- **文件**：`backend/services/system_manager.py`
- **问题**：数据库路径硬编码为 `BASE_DIR / "data" / "app.db"`，自定义 DB 路径时备份/恢复/健康检查失效
- **修复**：新增 `_get_db_file_path()` 从 `SQLALCHEMY_DATABASE_URI` 动态解析 SQLite 文件路径（兼容相对/绝对路径），MySQL 时返回 `None`。替换 4 处硬编码引用

### P2-12 supervisor.conf 路径修复
- **文件**：`deploy/supervisor.conf`
- **问题**：venv 路径指向宝塔可能不存在的 `/www/server/pyporject_evn/...`（含拼写错误）；Celery 进程默认启动但 `CELERY_ENABLED=False` 时无需
- **修复**：venv 路径改为项目本地 `venv/bin/`；Celery worker/beat 默认注释，仅 `CELERY_ENABLED=True` 时取消注释；添加路径确认说明

### P2-13 upgrade.sh 增量迁移说明
- **文件**：`deploy/upgrade.sh`
- **问题**：升级脚本缺少新配置项提醒、EMV 迁移步骤、升级前自动备份
- **修复**：
  - 步骤 0：升级前自动创建 `pre_update` 备份（zip 含 DB + .env）
  - 步骤 3：自动执行 `migrate_emv.py`（存在时）
  - 头部注释：列出 `.env` 新增配置项（`CELERY_ENABLED`、`CORS_ALLOW_ORIGINS`）及迁移注意事项
  - 重启步骤改为非阻断（进程不存在时 `|| true`）

### P2-14 nginx HTTPS 强制 + .installed 保护
- **文件**：`deploy/nginx.conf`、`deploy/onepress-nginx-snippet.conf`
- **问题**：nginx 仅 HTTP 无 HTTPS 模板；`.installed` 等敏感文件未禁止访问
- **修复**：
  - `nginx.conf`：HTTP 80 强制 301 跳转 HTTPS（保留安装接口 HTTP 可达）；新增 HTTPS 443 server 模板（含 SSL 证书占位 + HSTS）；降级模式 HTTP server 块
  - 敏感文件保护：`location ~ /\.(env|git|svn|ht|installed|gitignore)` → deny + 404
  - `onepress-nginx-snippet.conf`：同步添加 `.installed` 保护规则 + HSTS 注释

### P2-15 Fernet key 延迟派生（支持 APP_SECRET_KEY 热变更）
- **文件**：`backend/core/security.py`、`backend/config.py`
- **问题**：`_fernet = Fernet(...)` 在模块加载时固化，`.env` 修改 `APP_SECRET_KEY` 后无法生效（需重启）
- **修复**：
  - `security.py`：删除模块级 `_fernet` 变量，改为 `_get_fernet()` 函数每次调用时从 `get_settings()` 派生
  - `config.py`：新增 `clear_settings_cache()` 清除 `lru_cache`，配合热变更后调用

### P2-16 前端 EMV 漏斗补第10层卡片
- **文件**：`frontend/src/views/Strategy.vue`
- **问题**：前端 EMV 漏斗图仅显示 9 层，缺少第10层
- **修复**：`EMV_LAYERS` 数组补充 `{ key: '10_win_rate_observe', name: '胜率观察期', desc: '滚动24笔胜率 ≥ 15%（不足8笔不生效）' }`

---

## 四、变更文件清单

| # | 文件路径 | 变更类型 | 涉及问题 |
|---|---------|---------|---------|
| 1 | `main.py` | 修改 | P0-1, P0-4, P0-5, P1-8, P2-10 |
| 2 | `backend/config.py` | 修改 | P0-5, P1-8, P2-15 |
| 3 | `backend/strategy/engine.py` | 修改 | P0-2 |
| 4 | `backend/tasks/scheduled.py` | 确认 | P0-3（无需修复） |
| 5 | `backend/strategy/emv_strategy.py` | 修改 | P1-6 |
| 6 | `backend/strategy/scoring.py` | 修改 | P1-6 |
| 7 | `backend/services/backtest_engine.py` | 修改 | P1-7 |
| 8 | `backend/services/news_strategy.py` | 修改 | P1-9 |
| 9 | `backend/services/system_manager.py` | 修改 | P2-10, P2-11 |
| 10 | `backend/core/security.py` | 修改 | P2-15 |
| 11 | `frontend/package.json` | 修改 | P2-10 |
| 12 | `frontend/src/views/Strategy.vue` | 修改 | P1-6, P2-16 |
| 13 | `deploy/supervisor.conf` | 重写 | P2-12 |
| 14 | `deploy/upgrade.sh` | 重写 | P2-13 |
| 15 | `deploy/nginx.conf` | 重写 | P2-14 |
| 16 | `deploy/onepress-nginx-snippet.conf` | 修改 | P2-14 |

---

## 五、向后兼容性说明

- **配置项**：新增 `CORS_ALLOW_ORIGINS`（默认 `*`）和 `CELERY_ENABLED`（默认 `False`），不填则行为与旧版一致
- **数据库**：`Base.metadata.create_all` 自动建新表/新列，不删旧列，无需手动迁移
- **API**：无接口签名变更，前端无需同步更新
- **安全模块**：`_get_fernet()` 延迟派生对调用方透明，`encrypt_api_key`/`decrypt_api_key` 签名不变

---

## 六、建议的 Git Commit Message

```
fix: 策略交易系统 v1.1.0 全量问题修复（16项）

P0: 平仓巡检APScheduler兜底 / 冷却期自动恢复 / 默认密码告警 / CORS收紧
P1: EMV第10层补回 / 回测引擎支持EMV V7 / 调度器去重 / 新闻评分路径统一
P2: 版本号统一1.1.0 / DB路径动态读取 / supervisor路径修复 /
    upgrade.sh增量迁移 / nginx HTTPS+.installed保护 / Fernet热变更
```
