# 策略交易系统 · WordPress 式宝塔一键部署图文教程（Famous 5 分钟 / 0 基础版）

> 本教程 = 源码包自带的「傻瓜式部署手册」。
> 目标：让你像装 WordPress 一样，**宝塔添加网站 → 上传 zip → 解压 → 点击域名立刻看到安装向导 → 1 行命令 + 3 步 Web 安装向导 → 完成**。
> 全程**不需要理解 FastAPI / venv / uvicorn / Nginx**，照抄照点就行。

---

## 一、前置条件（一次性，装过就跳过）

| 软件 | 版本要求 | 装没装怎么看 |
|---|---|---|
| **宝塔面板** | 7.x / 8.x 任意正式版 | 浏览器能打开 `http://服务器IP:8888/xxxx安全入口` 即可 |
| **Nginx** | 1.20+（宝塔默认）| 宝塔 → 软件商店 → 已安装里有 Nginx 就行 |
| **Python** | 3.10 / 3.11 / 3.12 任意一个 | 宝塔 → 软件商店 → 装「**Python 项目管理器**」→ 里面装 Python 3.10+（推荐 3.11）|
| **MySQL**（可选，首次不装也行）| 5.7 / 8.x | **第一次强烈推荐直接勾选 SQLite**（零依赖，不用建库建账号）；等上线前再切 MySQL 即可 |
| **Redis**（可选，不是必须）| 5 / 6 / 7 | 不装也能跑核心交易/回测；要开 Celery 定时任务 / AI 新闻推送再装 |

> 💡 结论：第一次部署只要装好「宝塔 + Nginx + Python 项目管理器 3.10+」，5 分钟就够了。

---

## 二、Step 0 · 先准备 onepress zip（源码包）

### 0.1 如果你拿的是别人给你的打包好的 zip：
直接跳 **三、宝塔建站**。

### 0.2 如果你是开发者/运维，要自己从源码打 zip：
在 Windows 源码根目录（有 `main.py` 的那一层），**双击**这个文件：
- `0_一键打包_双击我→zip自动出现在桌面.pyw`（项目根，Windows 直接双击，不会弹黑框）

双击后 3~10 秒会发生：
1. 桌面自动生成 `strategy-trade-onepress-v1.0.0-YYYYMMDD-HHMMSS.zip`
2. **资源管理器自动打开桌面，并高亮选中这个 zip**（你立刻就能看到）
3. 弹提示框显示：文件数 / 大小 / 是否包含前端 dist
4. 桌面还会写一份 `_onepress_最新zip路径.txt`，防止弹窗被关找不到

> 要不要 build 前端：
> - 想解压后直接访问首页看到登录页：先 `cd frontend && npm install && npm run build`，再双击打包器（zip 里就带 `frontend/dist/`）
> - 想最快跑起来 / 不会前端：先不 build，打包出来也能用，`/install /docs /api /health` 全正常，等后面要前端了再 build 再重打包一次。

---

## 三、宝塔建站（1 分钟）

1. 宝塔左侧菜单 → **网站** → **添加站点**
2. 填：
   - **域名**：你的域名，例如 `trade.xxx.com`（没有域名就填服务器公网 IP，例如 `47.x.x.x`）
   - **根目录**：默认即可（例如 `/www/wwwroot/trade.xxx.com`），后面会用到
   - **FTP**：不创建
   - **数据库**：不创建（首次用 SQLite，零依赖）
   - **PHP**：选「**纯静态**」或「不创建」都行（我们跑 Python，不需要 PHP）
3. 点 **提交** → 站点创建完成。

---

## 四、上传 zip → 解压（1 分钟）

1. 宝塔 → 网站 → 找到刚才那一行 → 点最右的 **根目录**（四个字，不是「操作」按钮）
2. 进入文件管理器后，点 **上传** → 选桌面上的 `strategy-trade-onepress-v1.0.0-xxxx.zip` → 等上传完成
3. **右键 zip → 解压到当前目录**

### ✅ 解压正确验证（很重要，90% 的坑出在这里）
解压完后，在**当前文件管理器根下**（就是你刚点根目录进来的那一层），你应该能直接看到：
- `main.py`
- `requirements.txt`
- `.env.example`
- `index.html` ← 就是我们 WordPress 式的静态安装入口页
- `backend/`、`deploy/`、`frontend/`、`StrategyTradeLauncher/`

❌ 如果你看到的是：
> `strategy-trade-onepress-v1.0.0-xxxx/` ← 一个二级文件夹，点开才有 main.py

那就说明解压位置多了一层，请：
1. 双击进入这个二级文件夹 → **Ctrl+A 全选所有文件/目录**
2. 点右上角 **剪切**
3. 回站点根（`/www/wwwroot/trade.xxx.com`）→ **粘贴**
4. 现在 `main.py` 应该直接出现在根下了，正确。

---

## 五、点击域名 → **立刻看到安装向导**（真·WordPress 体验）

现在浏览器打开你的域名（`http://trade.xxx.com` 或服务器 IP），会看到漂亮的 **WordPress 式安装向导**（就是 zip 根那个 `index.html`）。

页面分 3 块：
### ① 后端启动自检（自动）
- ✅ **绿色（已启动）**：直接出现「▶️ 进入完整安装向导 /install」绿色大按钮 → 点它跳第六节
- ⚠️ **黄色（未启动）**：出现 1 行启动命令，一键复制 → 粘贴到宝塔终端回车

### ② 解压完整性自检（自动）
看是否 6 个 ✅（main.py / requirements.txt / deploy/onepress-install.sh / onepress-nginx-snippet.conf / 0_宝塔WordPress式一键搭建说明.htm）
- 有 ❌ → 回到第四节把 zip 解压到正确位置（main.py 要在根下）

### ③ 安装向导速览 + 验收 3 信号
给你心里有个数，一会 `/install` 里会做什么。

---

## 六、后端还没启动？→ 1 行命令（推荐，0 基础最稳）

如果刚才第 ① 块是黄色，就做这一步；已经绿色直接跳过。

1. 宝塔左侧 → **终端**（或 网站 → 点击「终端」按钮）
2. 复制向导页给的这一行，粘贴回车（一般长这样，页面里会帮你自动通配站点目录）：

```bash
cd /www/wwwroot/trade.xxx.com && bash deploy/onepress-install.sh
```

> 注意：把 `trade.xxx.com` 换成你**实际的站点根**，或者直接用向导页「📋 复制 1 行启动命令」按钮，它会自动用通配符帮你定位，不用手改。

### 这个脚本自动做什么？
- ✅ 找 Python 3.10+（含宝塔 pyenv 里装的）
- ✅ 创建 `.venv` 虚拟环境
- ✅ 清华镜像 `pip install -r requirements.txt`（失败自动退回官方源）
- ✅ 清理旧 uvicorn 进程（避免 8000 被占）
- ✅ 备份静态入口 `index.html` 到 `.bak`（避免覆盖后端 / 路由状态机）
- ✅ `nohup 后台启动 uvicorn 127.0.0.1:8000`，日志写到 `logs/uvicorn.log`
- ✅ 启动后探测 `/health`，最后一行出现 **`/health 探测返回 200`** 就代表后端 OK。

> 🧱 端口被占怎么办？脚本末尾会报错并提示：直接 `BACKEND_PORT=8001 bash deploy/onepress-install.sh` 改端口即可；记得同时改 Nginx 反代片段里的 8000。

---

## 七、回到安装向导页 → **进入完整 /install 向导 3 步**

后端起来后，刚才那一页黄色会变绿色「✅ 后端 uvicorn 已经在 8000 端口跑起来了」。

点绿色大按钮 **「▶️ 进入完整安装向导 /install」**，或者手动访问域名 `/install`。

### 7.1 ① 环境预检
- 自动测 Python 版本 / 磁盘 ≥ 5 GB / 内存 / MySQL&SQLite 连接 / Redis / 缺失 Py 包 / frontend dist
- **第一次最佳实践**：
  - ❌ MySQL 不通没关系（下一步勾 SQLite）
  - ❌ Redis 不通没关系（不装 Celery 也能跑核心功能）
  - 缺失 Py 包列了多少个不用管，下一步脚本会统一装

### 7.2 ② 填写配置（最关键的一步，就像 WordPress 填 wp-config）
按下面填：
| 项 | 填什么 | 备注 |
|---|---|---|
| 站点标题 | 随便，例如「我的交易机器人」 | 后面可改 |
| 运行环境 | 生产（宝塔部署推荐） | 本地调式才选开发 |
| 管理员账号 | **建议改掉 admin**，例如 `boss_zhangsan` | 长度 4~48，只允许字母/数字/_ - @ . |
| 管理员密码 | ⚠️ 至少 8 位，**字母+数字**（加符号更安全） | 填完**立刻存到密码管理器**：忘记只能删库重建 |
| 管理员昵称 | 随便，例如「超级管理员」| |
| APP_SECRET_KEY | **留空**，系统自动生成 64 位 | 换服务器一定要保留，否则所有用户 token 会失效 |
| ✅ 先试用 SQLite | **强烈建议第一次勾上** 🟢 | 零依赖，不用建数据库；以后再切 MySQL |
| Redis 主机/密码/DB | 没装 Redis 就默认 127.0.0.1 | 不影响后端启动 |
| 币安 / OKX API / 代理池 / AI 模型 | **全部留空** ❗ | 装好在前端或 `.env` 里改，填错反而容易启动失败 |

点 **【▶️ 运行安装（写入 .env → 建表 → 创建管理员）】** → **2~5 秒就好**。

安装接口会做：
1. 校验管理员账号密码（≥8 位 + 字母+数字）
2. 自动生成 `.env`（先把旧的 `.env` 备份成 `.env.bak.时间戳`）
3. 刷新 settings → 重新连数据库
4. `CREATE TABLE IF NOT EXISTS` 建所有表（策略模板 / 用户 / 订单 / 持仓 / 新闻 / 回测...）
5. 初始化种子数据（默认策略模板 + 演示新闻 / 开发环境会演示交易样例）
6. **用你刚才输入的账号密码创建管理员**（不再强制默认 `admin/Admin@2024`）
7. 写 `.installed` 标记（600 权限）→ 状态机关闭向导，以后访问 `/` 就不会重复安装了
8. **自动把静态入口 `index.html` 重命名为 `.bak`**，由后端状态机接管首页
9. 返回下一步三份配置：宝塔 Python 项目管理器字段 / 1 行命令 / Nginx 反代片段

### 7.3 ③ 安装完成 → 复制两份配置即可（复制粘贴工作）
**最小可用建议：只做「方案 B + 方案 C」两项（两行复制粘贴）**

#### 🟢 方案 B（最推荐 ⭐，复制 1 行 nohup 命令）
如果你刚才已经执行过 `bash deploy/onepress-install.sh`，这里**不用再做**；没做就复制粘贴回车一次。

#### 🟢 方案 C（建议必做，复制 Nginx 反代片段）
宝塔 → 网站 → 设置 → **配置文件**：
- ❌ **千万不要**删除原有整段 `server { listen 443 ssl http2; server_name trade.xxx.com; ssl_certificate /etc/letsencrypt/...; }` 等行（SSL 证书路径会丢）
- ✅ 只在 **`server {` 里面、现有 location 外面**，粘贴向导页「📋 复制 Nginx 反代片段」里的内容
- 把里面所有 `/www/wwwroot/trade.xxx.com` 占位路径改成你真实的站点根（一共 2~3 处）
- 点保存 → Nginx 自动重载

片段功能说明（不用背，了解即可）：
- `location /assets/`：前端静态 7 天缓存 + gzip
- `location ~ ^/(api|docs|redoc|openapi\.json|health|install)`：反代到 `127.0.0.1:8000`，带 XFF / WebSocket 升级头（币安行情、实时 AI 推送要用）
- `location /`：SPA fallback，找不到文件就返回 frontend/dist/index.html；如果还没构建前端，就 307 跳 `/docs`

---

## 八、验收 · 出现这 3 个信号 = Famous 5 秒完成 ✅

1. ✅ **/health**：域名+`/health` → 返回
```json
{
  "status": "ok",
  "installed": true,
  "installed_at": "2026-08-02 12:34:56"
}
```

2. ✅ **/docs**：域名+`/docs` → 出现 Swagger UI
   - 点 `POST /api/v1/auth/login` → Try it out → 填你在 7.2 输入的管理员账号密码 → Execute
   - Response 里出现 `access_token`（一段 JWT）→ OK
   - 点右上角 **Authorize** → `Bearer 粘贴刚才的 token` → 后面所有接口就能直接调了

3. ✅ **/ 首页**：
   - 若 onepress zip 带了 `frontend/dist`：看到登录页，用管理员账号直接登录即可
   - 没带前端：看到引导页（写着「后端已启动」）→ **也算正常**，`/docs` 能用就说明一切 OK；等要前端再 `cd frontend && npm install && npm run build` 再刷新

---

## 九、常用场景速查

### 9.1 想重装（换管理员密码 / 换数据库）
```bash
cd /www/wwwroot/trade.xxx.com
cp -a .env ".env.bak.$(date +%s)"   # 先备份配置
rm -f .installed                    # 删除安装标记
# 然后浏览器打开 /install 进入向导
# 完全干净再额外：rm -f trading_system.db 或宝塔数据库页 DROP 库
```

### 9.2 SQLite → 切 MySQL（上线前做一次）
1. 宝塔 → 数据库 → 添加数据库：字符集 **utf8mb4**，记好 `host/port/user/pass/dbname`
2. 编辑 `.env`：
   - 把 `DB_SQLITE_FALLBACK=` 那行清空（= 关掉 SQLite 模式）
   - 下面 `DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME / DB_CHARSET` 6 行填对
3. 重启 uvicorn：
```bash
cd /www/wwwroot/trade.xxx.com
kill $(cat logs/uvicorn.pid) 2>/dev/null ; rm -f logs/uvicorn.pid
bash deploy/onepress-install.sh
```
4. 第一次启动会自动建表；管理员账号因为换了 DB 要**重新在 `/install` 向导里建一次**（或用 DBeaver 迁 SQLite 数据过来）

### 9.3 看日志
```bash
cd /www/wwwroot/trade.xxx.com
tail -f logs/uvicorn.log           # 主日志：HTTP 请求 / Python 报错
tail -f logs/nohup.log             # 启动期 stdout/stderr
tail -f logs/celery_worker.log     # （可选）Celery 定时任务 / AI 新闻分析日志
tail -f logs/celery_beat.log       # （可选）Celery beat 调度日志
```

### 9.4 重启 / 停止后端
```bash
cd /www/wwwroot/trade.xxx.com
# 简单稳：再跑一次安装脚本（自动 kill 旧的）
bash deploy/onepress-install.sh

# 手动停
kill $(cat logs/uvicorn.pid) 2>/dev/null ; rm -f logs/uvicorn.pid
```

### 9.5 前端构建（需要看到漂亮仪表盘时做）
```bash
# 宝塔软件商店先装「Node 版本管理器」→ 装 Node 18+
cd /www/wwwroot/trade.xxx.com/frontend
npm install
npm run build
# 构建完刷新域名 /，直接看到登录页；不需要重启 uvicorn
```

### 9.6 生产守护（Supervisor，建议上线再开）
安装包自带 [deploy/supervisor.conf](../supervisor.conf)：
- `program:strategy_trade_api` = uvicorn API
- `program:strategy_trade_celery_worker` = Celery worker（AI 新闻 / 定时策略）
- `program:strategy_trade_celery_beat` = Celery beat（调度）
```bash
apt-get install supervisor -y          # Debian/Ubuntu
# yum install supervisor -y           # CentOS
cp /www/wwwroot/trade.xxx.com/deploy/supervisor.conf /etc/supervisor/conf.d/strategy-trade.conf
# 改 conf 里 3 处 directory= / environment=PATH 为你的真实路径
supervisorctl update && supervisorctl status
```

---

## 十、FAQ · 高频问题 Top 5

### Q1 访问域名 403 Forbidden / 502 Bad Gateway / 目录列表
- 403/目录列表：基本是 **第四节 zip 解压错位置**（main.py 不在根下）→ 回第四节剪切到根；或 **index.html 没在根**（看一眼文件管理器根下有没有 `index.html`，没有就重新在解压一次）
- 502：后端 uvicorn 没起来 → `tail -n 200 logs/uvicorn.log` 看报错
  - 常见：端口 8000 被占 → 改端口跑 `BACKEND_PORT=8001 bash deploy/onepress-install.sh`
  - 常见：缺依赖 → 重跑 `bash deploy/onepress-install.sh`（会再次 pip install）
  - 常见：DB 配错 → 编辑 `.env`，第一次推荐干脆切回 SQLite（`DB_SQLITE_FALLBACK=sqlite:///./trading_system.db`）

### Q2 访问域名显示 Nginx 默认页 / 还是旧站点内容
- 宝塔站点配置里 **server_name** 没填你的域名（或 SSL 证书段的 server_name）→ 检查
- 浏览器 Ctrl+F5 强制刷新 / 开无痕
- 你把 Nginx 片段贴错位置了（回第七节 7.3 方案 C：只贴片段别替换整段 server{}）

### Q3 管理员密码忘了怎么办
- 最简单：执行 9.1「想重装」→ 再进 /install 重设
- 不想动数据：直接改 DB（用户表里 bcrypt 密码 hash 字段），重写一个新 bcrypt hash 即可

### Q4 前端页面白屏、/assets 404
- 你没构建前端，或构建错位置：正确位置是 `项目根/frontend/dist/index.html` + `frontend/dist/assets/`
- 宝塔 Nginx 片段里 `/assets/` 的 alias 路径填错了（对照 7.3 复制的片段，用真实站点根替换占位路径）

### Q5 币安/OKX 连不上、新闻一直不更新
- 服务器在国内 → 基本是网络被墙：在 `/install` 向导里「代理池」填 HTTP 代理（例如你自己的出口代理）
- 建议先用测试网（/install 向导里 BINANCE_TESTNET=true / OKX_TESTNET=true），等跑稳再切实盘
- 实盘一定要先开风控 / 仓位上限 / 最大回撤，不要把生产账号直接接策略

---

## 十一、1 页速查命令卡（宝塔终端里复制）
```bash
# 0) 站点根
cd /www/wwwroot/trade.xxx.com

# 1) 一键启动后端（最稳，含 venv + pip + nohup + 探测 /health）
bash deploy/onepress-install.sh

# 2) 看日志
tail -f logs/uvicorn.log
tail -f logs/nohup.log

# 3) 停 / 重启
kill $(cat logs/uvicorn.pid) 2>/dev/null; rm -f logs/uvicorn.pid
bash deploy/onepress-install.sh

# 4) 探活
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# 5) 重装向导（先备份配置！）
cp -a .env ".env.bak.$(date +%s)"; rm -f .installed
# 浏览器打开 /install

# 6) 前端构建（需要仪表盘）
cd frontend && npm install && npm run build && cd ..
```

---

## 十二、关键文件速查表（源码包解压出来的）
| 路径 | 作用 |
|---|---|
| `index.html` | WordPress 式静态安装入口（用户点域名立刻看到安装向导，启动后端后自动 rename 到 .bak）|
| `main.py` | FastAPI 后端入口；状态机：未安装访问 / 自动 307 跳 /install；安装完成锁 `/install` |
| `0_宝塔WordPress式一键搭建说明.htm` | 与本 .md 对应，彩色图文版，双击即可看，不用开编辑器 |
| `deploy/onepress-install.sh` | 宝塔 1 行启动脚本（找 Python / 建 venv / 清华 pip / nohup uvicorn / 探测 health）|
| `deploy/onepress-nginx-snippet.conf` | 复制粘贴型 Nginx 反代片段（assets 缓存 + API/docs/health/install 反代 + SPA fallback）|
| `deploy/make_onepress_zip.py` | 源码打包 onepress zip 的脚本（开发者用，一般直接双击根那个 .pyw）|
| `deploy/supervisor.conf` | 生产守护 3 进程模板（API / Celery Worker / Celery Beat）|
| `deploy/01_部署教程/` | 就是你现在看的这份教程 |
| `.env.example` | 配置模板（/install 向导会根据你填的内容生成最终 `.env`）|
| `backend/db/seed_data.py` | 安装向导里建表 + 初始化管理员（admin_username/admin_password 自定义）的种子函数 |
| `StrategyTradeLauncher/Step0_一键启动后端_8000_HTA启动器.hta` | Windows 本地双击启动器（绕 ExecutionPolicy/AppLocker）|

---

✅ **到这里你已经会部署了**：跟着第二节 → 第八节做一遍，就是 WordPress Famous 5 分钟体验。祝你顺利上线交易！
