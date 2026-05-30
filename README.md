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
│   └── github-api.js       # GitHub API 写回工具
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
    └── push_daily.py       # 每日推送数据到仓库的脚本
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

## 📝 License

MIT
