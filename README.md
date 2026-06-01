# IGN Daily News

> 📖 **AI Agent / 开发者？请先读 [→ AGENT_HANDOFF.md](AGENT_HANDOFF.md)** — 完整的项目交接文档，包含架构、数据格式、翻译规则、常见坑、脚本说明等一切。

---

一个个人化的IGN每日新闻翻译协作平台。每天早晨自动抓取IGN新闻，在网页上选择需要翻译的文章，翻译完成后以左译文-右原文的对照形式呈现，并支持词库的在线编辑。

🌐 **在线访问**: https://zenotzz.github.io/ign-daily/

## ✨ 功能

- 📰 **每日新闻列表**：每天早晨8:30自动抓取IGN前24小时新闻
- ✅ **翻译选择**：在网页上勾选需要翻译的文章，无需在聊天里发编号
- 🔀 **左右对照**：PC端打开译文时左侧显示中文翻译、右侧显示IGN原文
- 📚 **历史记录**：保留每日新闻和翻译归档
- 📖 **词库管理**：在线查看、编辑游戏/影视/公司/人物/媒体名称的中英对照
- 📱 **响应式**：移动端和PC端均适配

## 📁 目录结构

```
ign-daily/
├── index.html              # 首页（当日新闻列表 + 翻译选择）
├── article.html            # 单篇译文阅读页（左译文右原文）
├── dict.html               # 词库管理页
├── history.html            # 历史归档页
├── assets/
│   ├── app.js              # 前端逻辑
│   ├── style.css           # 样式
│   └── alpine.min.js       # 本地托管 AlpineJS
├── data/
│   ├── dict.json           # 词库
│   ├── 2026-05-28/         # 每日数据目录
│   │   ├── index.json      # 当日新闻索引
│   │   ├── requests.json   # 用户翻译请求记录
│   │   └── translations/
│   │       ├── 05.json     # 单篇译文（含中英对照段落）
│   │       └── ...
│   └── ...
└── scripts/
    ├── ign_rss_incremental.py # RSS 增量抓取
    ├── translate_pipeline.py  # 翻译预处理/后处理
    └── git_push.py            # PAT 推送工具
```

## 🚀 本地预览

```bash
# 用任意静态服务器，例如 Python
python -m http.server 8000
# 然后访问 http://localhost:8000
```

## 🔧 GitHub Pages 部署

1. 在仓库 Settings → Pages 中：
   - Source 选 `Deploy from a branch`
   - Branch 选 `main` / `(root)`
2. 等待几分钟 GitHub 自动部署
3. 访问 https://zenotzz.github.io/ign-daily/

## 🔑 写回功能（在网页上修改词库等）

需要 GitHub Personal Access Token (PAT)：
- 创建：Settings → Developer settings → Personal access tokens → Fine-grained tokens
- 权限：`Contents: Read and write`、目标仓库 `ign-daily`
- 在网页右上角设置图标里粘贴 token（保存在浏览器 localStorage，不上传任何服务器）

## 📜 数据规范

详见 [data/README.md](data/README.md)。

## ⚙️ 技术说明

### 为什么 AlpineJS 是本地托管而非 CDN？

`assets/alpine.min.js` 是从 unpkg.com 下载后本地托管的。原因：

1. **Tracking Prevention / 广告拦截器**：某些浏览器（如 Edge）和插件会屏蔽 `unpkg.com`、`cdn.jsdelivr.net` 等 CDN 域名，导致 AlpineJS 加载失败，`article.html` 的所有 `x-show`、`x-text`、`x-for` 等 Alpine 指令全部失效，页面按钮和右侧对照区域不渲染。
2. **企业内网**：部分企业网络也会限制外部 CDN 资源。

### 文章页右侧空白怎么办？

`article.html` 的右侧面板（IGN 原文 / 降级英文段落）和所有功能按钮（对照、润色、词库等）依赖 AlpineJS 正常工作。如果右侧空白，请检查：

1. **浏览器 Console**（F12）是否有 `Alpine Expression Error`？如有，说明 `article` 数据的某个字段在渲染时仍为 `null`，需要加 `?.` 可选链。
2. **浏览器是否屏蔽了 CDN 资源**（Console 中是否有 `Tracking Prevention blocked access to storage` 警告）？本项目的 AlpineJS 已本地托管，通常无需担心。
3. **浏览器缓存**：按 `Ctrl+F5` 强制刷新。

右侧 IGN 原文默认通过 iframe 加载，由于 IGN 设置了 `X-Frame-Options: DENY`，iframe 会被浏览器拒绝。5 秒后将自动降级为显示抓取的英文原文段落（与左侧中文译文一一对应）。

### 关键变更记录

- **2026-06-01**: 修复 article.html 中 `article.pending_dict` 缺少可选链 `?.` 导致的 Alpine 表达式异常；所有按钮和右侧 pane 移除 `hidden sm:inline / lg:inline-flex / hidden lg:block` 响应式隐藏类；AlpineJS 从 unpkg CDN 改为 `assets/alpine.min.js` 本地托管。修复旧翻译 JSON 缺少 `url`/`en_title` 导致 iframe 右侧空白的问题；pipeline `--post` 模式新增自动补 `url`/`en_title`。
- **2026-06-01**: 脚本统一从仓库根目录推导路径，三连校验不再扫描 `repo/ign-daily/data` 或旧 `C:\Users\Administrator\.openclaw\workspace`；词库统一优先使用 `data/dict.json`；副标题字段统一为 `subtitle`。
- **2026-06-01**: 「复制全文」改为同时写入纯文本和 HTML 段落，粘贴到腾讯文档/Word/飞书时保留原译文分段。
- **2026-06-01**: 首页发布时间兼容 `pub_date`，并回填 2026-06-01 数据的 `publish_time_cn`；`agent_doctor.py` 新增缺失发布时间检查。
- **2026-06-01**: RSS 增量抓取迁移到 GitHub Actions `.github/workflows/hourly-rss.yml`；CI 使用 `IGN_DAILY_SKIP_GIT=1` 让脚本只写数据，再由 workflow 跑 `rss_queue_check.py`/`agent_doctor.py` 后提交。
- **2026-06-02**: 新增网页可视化自动化开关 `data/automation-config.json`。标题摘要和正文可分别选择 `openclaw` 或 `api`，并可切换 `deepseek-v4-flash`/`deepseek-v4-pro`；API 模式读取 GitHub Secret `TRANSLATOR_API_KEY`，严格跑现有校验脚本，不通过不 push。
- **2026-06-02**: 设置面板新增“立即运行 API 翻译”按钮，会先保存当前开关，再触发 GitHub Actions `api-translation.yml` 的 `workflow_dispatch`。浏览器里保存的 GitHub PAT 需要具备 Actions 写权限。
- **2026-06-02**: 每小时 RSS 后新增 `scripts/article_cache.py`，把干净英文正文、封面图、正文图缓存到 `data/{date}/sources/NN.json`。API 标题摘要和正文翻译优先复用缓存，减少重复抓取和 token 浪费。
- **2026-06-02**: 夜间学习也接入 `data/automation-config.json.nightly_learner`，可在网页里切换 `openclaw` / `api`。API 路径由 `.github/workflows/nightly-style.yml` 调用 `scripts/nightly_style_api.py` 更新 `STYLE_PROFILE.md`。

## 📝 License

MIT
