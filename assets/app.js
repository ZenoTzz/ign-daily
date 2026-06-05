// ign-daily / app.js

// ====== 暗黑模式（全局，所有页面必须在加载时调用） ======
function initDarkMode() {
  const saved = localStorage.getItem('theme') || 'auto';
  applyTheme(saved);
}
function applyTheme(theme) {
  const html = document.documentElement;
  let isDark = false;
  if (theme === 'dark') isDark = true;
  else if (theme === 'light') isDark = false;
  else { isDark = window.matchMedia('(prefers-color-scheme: dark)').matches; }
  html.classList.toggle('dark', isDark);
}
function toggleTheme() {
  const cur = localStorage.getItem('theme') || 'auto';
  const next = cur === 'dark' ? 'light' : (cur === 'light' ? 'auto' : 'dark');
  localStorage.setItem('theme', next);
  applyTheme(next);
  return next;
}
(function(){ try { initDarkMode(); } catch(_){} })();
window.appTheme = { initDarkMode, applyTheme, toggleTheme };

// ---- GitHub API helper (用于写回) ----
const GH = {
  owner: 'ZenoTzz',
  repo: 'ign-daily',
  branch: 'main',
  apiBase: 'https://api.github.com',
  authHeader() {
    const token = localStorage.getItem('gh_token') || '';
    if (!token) return '';
    const type = localStorage.getItem('gh_token_type') || '';
    if (type === 'oauth' || /^(gho_|ghu_|ghs_|ghr_)/.test(token)) return `Bearer ${token}`;
    return `token ${token}`;
  },

  async getFile(path) {
    const url = `${this.apiBase}/repos/${this.owner}/${this.repo}/contents/${path}?ref=${this.branch}&t=${Date.now()}`;
    const headers = {};
    const auth = this.authHeader();
    if (auth) headers.Authorization = auth;
    const res = await fetch(url, { headers, cache: 'no-store' });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
    const data = await res.json();
    return {
      sha: data.sha,
      content: decodeURIComponent(escape(atob(data.content)))
    };
  },

  async putFile(path, content, message, retry = 2) {
    const token = localStorage.getItem('gh_token');
    if (!token) throw new Error('未配置 GitHub Token，请在右上角 ⚙️ 设置');

    const existing = await this.getFile(path);
    const body = {
      message,
      content: btoa(unescape(encodeURIComponent(content))),
      branch: this.branch,
      ...(existing ? { sha: existing.sha } : {})
    };

    const res = await fetch(`${this.apiBase}/repos/${this.owner}/${this.repo}/contents/${path}`, {
      method: 'PUT',
      headers: {
        Authorization: this.authHeader(),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      // 409 sha mismatch → 重试（拿最新sha再PUT）
      if (res.status === 409 && retry > 0) {
        await new Promise(r => setTimeout(r, 300));
        return this.putFile(path, content, message, retry - 1);
      }
      const err = await res.json().catch(() => ({}));
      throw new Error(`PUT ${path} failed: ${res.status} ${err.message || ''}`);
    }
    return res.json();
  },

  async deleteFile(path, sha, message) {
    const token = localStorage.getItem('gh_token');
    if (!token) throw new Error('未配置 GitHub Token，请在右上角 ⚙️ 设置');
    const res = await fetch(`${this.apiBase}/repos/${this.owner}/${this.repo}/contents/${path}`, {
      method: 'DELETE',
      headers: {
        Authorization: this.authHeader(),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ message, sha, branch: this.branch })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(`DELETE ${path} failed: ${res.status} ${err.message || ''}`);
    }
    return res.json();
  },

  async dispatchWorkflow(workflowFile, inputs = {}) {
    const token = localStorage.getItem('gh_token');
    if (!token) throw new Error('未配置 GitHub Token，请在右上角 ⚙️ 设置');
    const res = await fetch(`${this.apiBase}/repos/${this.owner}/${this.repo}/actions/workflows/${workflowFile}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: this.authHeader(),
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ref: this.branch, inputs })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(`触发 ${workflowFile} 失败: ${res.status} ${err.message || ''}`);
    }
    return true;
  }
};

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function githubDeviceLogin(clientId, onStatus) {
  const id = String(clientId || '').trim();
  if (!id) throw new Error('GitHub OAuth Client ID is required.');
  const requestBody = new URLSearchParams({
    client_id: id,
    scope: 'repo workflow'
  });
  const codeRes = await fetch('https://github.com/login/device/code', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: requestBody
  });
  if (!codeRes.ok) throw new Error(`GitHub device code failed: ${codeRes.status}`);
  const codeData = await codeRes.json();
  if (codeData.error) throw new Error(codeData.error_description || codeData.error);
  onStatus?.(`Open ${codeData.verification_uri} and enter code ${codeData.user_code}`);
  try { window.open(codeData.verification_uri, '_blank', 'noopener,noreferrer'); } catch (_) {}

  let interval = Number(codeData.interval || 5);
  const deadline = Date.now() + Number(codeData.expires_in || 900) * 1000;
  while (Date.now() < deadline) {
    await sleep(interval * 1000);
    const tokenBody = new URLSearchParams({
      client_id: id,
      device_code: codeData.device_code,
      grant_type: 'urn:ietf:params:oauth:grant-type:device_code'
    });
    const tokenRes = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: tokenBody
    });
    if (!tokenRes.ok) throw new Error(`GitHub token exchange failed: ${tokenRes.status}`);
    const tokenData = await tokenRes.json();
    if (tokenData.access_token) return tokenData;
    if (tokenData.error === 'authorization_pending') {
      onStatus?.(`Waiting for GitHub authorization: ${codeData.user_code}`);
      continue;
    }
    if (tokenData.error === 'slow_down') {
      interval += 5;
      continue;
    }
    throw new Error(tokenData.error_description || tokenData.error || 'GitHub authorization failed.');
  }
  throw new Error('GitHub authorization expired. Start login again.');
}

// ---- News-day helpers ----
function todayBeijingDate() {
  // 新闻日按北京时间 08:00 分界：08:00 后归入下一天的数据目录。
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const beijing = new Date(utc + 8 * 3600 * 1000);
  if (beijing.getHours() >= 8) {
    beijing.setDate(beijing.getDate() + 1);
  }
  const y = beijing.getFullYear();
  const m = String(beijing.getMonth() + 1).padStart(2, '0');
  const d = String(beijing.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

// ---- Main app state (Alpine) ----
function appData() {
  return {
    loading: true,
    error: '',
    data: null,
    currentDate: '',
    availableDates: [],
    availableDateMeta: {},
    datePickerMonth: '',
    showDatePicker: false,
    showMobileMenu: false,
    selected: [],
    exportBasket: [],
    copyBtnText: '📋 复制摘要',
    filterCat: 'all',
    showSettings: false,
    token: localStorage.getItem('gh_token') || '',
    oauthClientId: localStorage.getItem('github_oauth_client_id') || '',
    oauthLoggingIn: false,
    oauthStatus: '',
    automationConfig: {
      title_translator: 'openclaw',
      fulltext_translator: 'openclaw',
      nightly_learner: 'openclaw',
      api_provider: 'openai-compatible',
      api_model: 'deepseek-v4-flash',
      api_title_model: 'deepseek-v4-flash',
      api_fulltext_model: 'deepseek-v4-pro',
      api_nightly_model: 'deepseek-v4-flash',
      api_title_thinking: 'disabled',
      api_fulltext_thinking: 'disabled',
      api_nightly_thinking: 'disabled',
      api_compare_thinking: 'disabled',
      api_base_url: 'https://api.deepseek.com',
      api_fulltext_batch: '5',
      compare_models: ['deepseek-v4-pro', 'deepseek-v4-flash'],
      api_models: [
        {
          label: 'DeepSeek V4 Pro',
          model: 'deepseek-v4-pro',
          base_url: 'https://api.deepseek.com',
          input_cache_hit_usd_per_million: 0.003625,
          input_cache_miss_usd_per_million: 0.435,
          output_usd_per_million: 0.87
        },
        {
          label: 'DeepSeek V4 Flash',
          model: 'deepseek-v4-flash',
          base_url: 'https://api.deepseek.com',
          input_cache_hit_usd_per_million: 0.0028,
          input_cache_miss_usd_per_million: 0.14,
          output_usd_per_million: 0.28
        }
      ]
    },
    automationSaving: false,
    automationTriggering: false,
    comparisonTriggeringId: null,
    rssTriggering: false,
    automationExpanded: false,
    filteredRss: [],
    showFilteredPanel: false,
    filteredRestoringUrl: '',
    translationFailures: {},
    toast: '',

    // 全局待确认词库
    globalPending: [],
    showPendingPanel: false,
    pendingQueue: [],
    pendingProcessing: false,

    // 主题
    themeIcon: '🌗',
    // 全局搜索
    showGlobalSearch: false,
    searchQuery: '',
    searchResults: [],
    searchLoading: false,
    searchTimer: null,
    searchCache: null,  // 历史文章总表，加载一次

    // 润色过的文章 ID 集合
    polishedIds: new Set(),

    async init() {
      // 初始主题图标
      const cur = localStorage.getItem('theme') || 'auto';
      this.themeIcon = cur === 'dark' ? '☀️' : (cur === 'light' ? '🌒' : '🌗');
      this.loadExportBasket();
      // 马上绑 beforeunload 保护
      window.addEventListener('beforeunload', (e) => {
        if (this.pendingProcessing || this.pendingQueue.length > 0) {
          e.preventDefault();
          e.returnValue = '后台还有未保存的词库修改，确定要离开吗？';
          return e.returnValue;
        }
      });
      try {
        await this.loadAutomationConfig();
        this.triggerRssOnRefresh();
        const date = new URLSearchParams(location.search).get('date') || todayBeijingDate();
        this.currentDate = date;
        // 加载可用日期列表
        try {
          const ilRes = await fetch('data/index-list.json?t=' + Date.now(), { cache: 'no-store' });
          if (ilRes.ok) {
            const il = await ilRes.json();
            const rows = Array.isArray(il) ? il : (il.dates || []).map(date => ({ date }));
            this.availableDates = rows.map(x => x.date || x).filter(Boolean).sort().reverse();
            this.availableDateMeta = {};
            rows.forEach(x => {
              const d = x.date || x;
              if (d) this.availableDateMeta[d] = x;
            });
          }
        } catch (_) {}
        this.datePickerMonth = date.slice(0, 7);
        const res = await fetch(`data/${date}/index.json?t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) {
          // 找不到今日，回退尝试最近一天
          this.error = `${date} 还没有数据，请等待早晨8:30的cron推送，或访问 历史 页面查看过往内容。`;
          this.loading = false;
          return;
        }
        this.data = await res.json();
        // 按发布时间从新到旧排序
        if (this.data && this.data.articles) {
          this.data.articles.sort((a, b) => (b.publish_time_cn || b.pub_date || b.pubDate_cst || '').localeCompare(a.publish_time_cn || a.pub_date || a.pubDate_cst || ''));
        }
        await this.loadFilteredRss(date);

        // 同步 requests.json：把已请求但还没翻译/复核的标记为 requested
        try {
          const reqRes = await fetch(`data/${date}/requests.json?t=${Date.now()}`, { cache: 'no-store' });
          if (reqRes.ok) {
            const reqData = await reqRes.json();
            const requested = new Set(reqData.requested_ids || []);
            const requestedUrls = new Set((reqData.requested_articles || []).map(x => x.url).filter(Boolean));
            for (const a of this.data.articles) {
              if ((requestedUrls.has(a.url) || requested.has(a.id)) && !['done', 'needs_review'].includes(a.translation_status)) {
                a.translation_status = 'requested';
              }
            }
          }
        } catch (_) { /* 没有 requests.json 是正常的 */ }

        // 同步 API 质检失败记录：显示为“需复核”，避免用户只看到“翻译中”
        this.translationFailures = {};
        try {
          const failRes = await fetch(`data/${date}/translation_failures.json?t=${Date.now()}`, { cache: 'no-store' });
          if (failRes.ok) {
            const failData = await failRes.json();
            this.translationFailures = failData.items || {};
            for (const a of this.data.articles) {
              const f = this.translationFailures[String(a.id)];
              if (f && a.translation_status !== 'done') {
                a.translation_status = 'needs_review';
                a.translation_error = f.reason || a.translation_error || 'API 质检未通过';
                a.translation_path = f.translation_path || a.translation_path;
                if (f.model) a.translator_model = f.model;
              }
            }
          }
        } catch (_) { /* 没有失败记录是正常的 */ }

        // 加载润色索引
        this.polishedIds = new Set();
        try {
          const polRes = await fetch(`data/${date}/polished/_index.json?t=${Date.now()}`, { cache: 'no-store' });
          if (polRes.ok) {
            const polIdx = await polRes.json();
            this.polishedIds = new Set(Object.keys(polIdx).map(k => parseInt(k)));
          }
        } catch (_) { /* 没有润色索引是正常的 */ }

        this.loading = false;

        // 恢复之前的筛选/滚动状态
        this.restoreState();

        // 加载全局待确认词库
        this.loadGlobalPending();
      } catch (e) {
        console.error(e);
        this.error = '加载失败：' + e.message;
        this.loading = false;
      }
    },


    // ==== 日期导航 ====
    navigateDate(direction) {
      const idx = this.availableDates.indexOf(this.currentDate);
      let newIdx;
      if (direction === 'prev') {
        // 上一天 = 日期列表中当前位置的下一个（因为是倒序）
        newIdx = idx + 1;
      } else {
        newIdx = idx - 1;
      }
      if (newIdx >= 0 && newIdx < this.availableDates.length) {
        window.location.href = `?date=${this.availableDates[newIdx]}`;
      }
    },
    canGoPrev() {
      const idx = this.availableDates.indexOf(this.currentDate);
      return idx < this.availableDates.length - 1;
    },
    canGoNext() {
      const idx = this.availableDates.indexOf(this.currentDate);
      return idx > 0;
    },
    goToDate(d) {
      window.location.href = `?date=${d}`;
    },
    datePickerMonthLabel() {
      const [y, m] = String(this.datePickerMonth || this.currentDate.slice(0, 7)).split('-');
      return `${y}年${Number(m)}月`;
    },
    shiftDatePickerMonth(delta) {
      const base = this.datePickerMonth || this.currentDate.slice(0, 7);
      const [y, m] = base.split('-').map(Number);
      const d = new Date(y, m - 1 + delta, 1);
      this.datePickerMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    },
    dateCalendarCells() {
      const month = this.datePickerMonth || this.currentDate.slice(0, 7);
      const [year, mon] = month.split('-').map(Number);
      const first = new Date(year, mon - 1, 1);
      const days = new Date(year, mon, 0).getDate();
      const leading = (first.getDay() + 6) % 7;
      const cells = [];
      for (let i = 0; i < leading; i++) cells.push({ key: `e-${month}-${i}` });
      const available = new Set(this.availableDates || []);
      for (let day = 1; day <= days; day++) {
        const date = `${year}-${String(mon).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const meta = this.availableDateMeta?.[date] || {};
        cells.push({
          key: date,
          date,
          day,
          available: available.has(date),
          total: meta.total || ''
        });
      }
      while (cells.length % 7) cells.push({ key: `t-${month}-${cells.length}` });
      return cells;
    },
    isToday() {
      return this.currentDate === todayBeijingDate();
    },

    async refreshAll() {
      // 使用 location.reload 硬刷，避免状态吐不干净问题
      // 追加 cache-bust 参数并跳到不带 query的纯净 url
      const url = new URL(location.href);
      url.searchParams.set('_t', Date.now());
      location.href = url.toString();
    },

    saveState() {
      try {
        sessionStorage.setItem('ign_index_state', JSON.stringify({
          filterCat: this.filterCat,
          scrollY: window.scrollY,
          date: this.data?.date,
          ts: Date.now()
        }));
      } catch (_) {}
    },

    restoreState() {
      try {
        const raw = sessionStorage.getItem('ign_index_state');
        if (!raw) return;
        const s = JSON.parse(raw);
        // 超过一天过期
        if (Date.now() - s.ts > 24 * 3600 * 1000) return;
        if (s.date !== this.data?.date) return;
        if (s.filterCat) this.filterCat = s.filterCat;
        // 等 DOM 渲染完再滚到原位置
        this.$nextTick(() => {
          setTimeout(() => {
            window.scrollTo({ top: s.scrollY, behavior: 'instant' });
          }, 50);
        });
      } catch (_) {}
    },

    get categories() {
      if (!this.data) return [];
      const counts = { all: this.data.articles.length };
      for (const a of this.data.articles) {
        counts[a.category] = (counts[a.category] || 0) + 1;
      }
      const order = ['游戏新闻','评测评分','影视资讯','人物新闻','行业动态','科技新闻','盘点推荐'];
      const list = [{ key: 'all', label: '全部', count: counts.all }];
      for (const c of order) {
        if (counts[c]) list.push({ key: c, label: c, count: counts[c] });
      }
      return list;
    },

    get filteredArticles() {
      if (!this.data) return [];
      if (this.filterCat === 'all') return this.data.articles;
      if (this.filterCat === '__translated__') {
        return this.data.articles.filter(a => a.translation_status === 'done');
      }
      if (this.filterCat === '__polished__') {
        return this.data.articles.filter(a => this.polishedIds.has(a.id));
      }
      return this.data.articles.filter(a => a.category === this.filterCat);
    },

    get translatedCount() {
      if (!this.data) return 0;
      return this.data.articles.filter(a => a.translation_status === 'done').length;
    },

    getCatIcon(category) {
      const map = {
        '游戏新闻': 'gamepad',
        '评测评分': 'star',
        '影视资讯': 'film',
        '人物新闻': 'sparkle',
        '行业动态': 'briefcase',
        '科技新闻': 'microscope',
        '盘点推荐': 'list'
      };
      return map[category] || 'gamepad';
    },

    getCatColor(catKey) {
      if (catKey === 'all') return 'var(--accent)';
      const map = {
        '游戏新闻': '#e50914',
        '评测评分': '#f59e0b',
        '影视资讯': '#8b5cf6',
        '人物新闻': '#ec4899',
        '行业动态': '#3b82f6',
        '科技新闻': '#06b6d4',
        '盘点推荐': '#22c55e'
      };
      return map[catKey] || '#6b7280';
    },

    get requestedCount() {
      if (!this.data) return 0;
      return this.data.articles.filter(a => a.translation_status === 'requested').length;
    },

    get requestedArticles() {
      if (!this.data) return [];
      return this.data.articles.filter(a => a.translation_status === 'requested');
    },

    get needsReviewCount() {
      if (!this.data) return 0;
      return this.data.articles.filter(a => a.translation_status === 'needs_review').length;
    },

    reviewReason(art) {
      return art?.translation_error || this.translationFailures?.[String(art?.id)]?.reason || 'API 质检未通过，请人工复核';
    },

    get visibleFilteredRss() {
      return (this.filteredRss || []).filter(a => (a.status || 'filtered') !== 'ignored');
    },

    get filteredRssCount() {
      return this.visibleFilteredRss.length;
    },

    async loadFilteredRss(date = this.currentDate) {
      try {
        const res = await fetch(`data/${date}/filtered_rss.json?t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) {
          this.filteredRss = [];
          return;
        }
        const rows = await res.json();
        this.filteredRss = Array.isArray(rows) ? rows : [];
      } catch (_) {
        this.filteredRss = [];
      }
    },

    async readGithubJson(path, fallback) {
      const file = await GH.getFile(path);
      if (!file) return { value: fallback, sha: null };
      try {
        return { value: JSON.parse(file.content), sha: file.sha };
      } catch (_) {
        return { value: fallback, sha: file.sha };
      }
    },

    buildRestoredArticle(item, nextId) {
      return {
        id: nextId,
        category: '游戏新闻',
        emoji: '🎮',
        en_title: item.title || '',
        cn_title: item.title || '',
        summary: '',
        url: item.url,
        publish_time_cn: item.pubDate_cst || '',
        pub_date: item.pubDate_cst || '',
        cover_image: '',
        translation_status: 'none'
      };
    },

    async restoreFilteredArticle(item) {
      if (!item || !item.url || !this.data?.date) return;
      try {
        this.filteredRestoringUrl = item.url;
        const date = this.data.date;
        const indexPath = `data/${date}/index.json`;
        const filteredPath = `data/${date}/filtered_rss.json`;
        const needPath = `data/${date}/need_titles.json`;

        const indexRead = await this.readGithubJson(indexPath, { date, articles: [], total: 0 });
        const idx = indexRead.value && Array.isArray(indexRead.value.articles)
          ? indexRead.value
          : { date, articles: [], total: 0 };
        if (idx.articles.some(a => a.url === item.url)) {
          this.flash('这篇已经在新闻列表里');
          this.filteredRss = this.filteredRss.filter(a => a.url !== item.url);
          await GH.putFile(filteredPath, JSON.stringify(this.filteredRss, null, 2) + '\n', `rss filter: remove restored duplicate for ${date}`);
          return;
        }

        const maxId = idx.articles.reduce((m, a) => Math.max(m, Number(a.id) || 0), 0);
        const article = this.buildRestoredArticle(item, maxId + 1);
        idx.articles.push(article);
        idx.articles.sort((a, b) => (b.publish_time_cn || b.pub_date || b.pubDate_cst || '').localeCompare(a.publish_time_cn || a.pub_date || a.pubDate_cst || ''));
        idx.total = idx.articles.length;

        const filteredAll = (this.filteredRss || []).filter(a => a.url !== item.url);
        const needRead = await this.readGithubJson(needPath, []);
        const need = Array.isArray(needRead.value) ? needRead.value : [];
        if (!need.some(q => q.url === item.url)) {
          need.push({
            id: article.id,
            url: article.url,
            en_title: article.en_title,
            pub_date: article.pub_date
          });
        }

        const histRead = await this.readGithubJson('data/index-list.json', []);
        const hist = Array.isArray(histRead.value) ? histRead.value : [];
        const row = hist.find(x => x.date === date);
        if (row) row.total = idx.total;
        else hist.push({ date, total: idx.total, translated: 0, translatedTitles: [] });
        hist.sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));

        await GH.putFile(indexPath, JSON.stringify(idx, null, 2) + '\n', `rss filter: restore article #${article.id} for ${date}`);
        await GH.putFile(needPath, JSON.stringify(need, null, 2) + '\n', `rss filter: queue restored title #${article.id}`);
        await GH.putFile(filteredPath, JSON.stringify(filteredAll, null, 2) + '\n', `rss filter: remove restored article for ${date}`);
        await GH.putFile('data/index-list.json', JSON.stringify(hist, null, 2) + '\n', `rss filter: update index-list for ${date}`);

        this.filteredRss = filteredAll;
        this.data = idx;
        if (this.isApiMode('title_translator')) {
          await GH.dispatchWorkflow('api-translation.yml', this.apiTranslationInputs());
          this.flash('已恢复入库，并触发 API 标题/摘要翻译', 4500);
        } else {
          this.flash('已恢复入库，OpenClaw 会处理标题/摘要', 4500);
        }
      } catch (e) {
        this.flash('恢复失败：' + e.message, 6000);
      } finally {
        this.filteredRestoringUrl = '';
      }
    },

    async ignoreFilteredArticle(item) {
      if (!item || !item.url || !this.data?.date) return;
      try {
        const filteredPath = `data/${this.data.date}/filtered_rss.json`;
        const updated = (this.filteredRss || []).map(a => (
          a.url === item.url ? { ...a, status: 'ignored', ignored_at_cn: new Date().toLocaleString('zh-CN', { hour12: false }) } : a
        ));
        await GH.putFile(filteredPath, JSON.stringify(updated, null, 2) + '\n', `rss filter: ignore article for ${this.data.date}`);
        this.filteredRss = updated;
        this.flash('已忽略，保留期后会自动清理');
      } catch (e) {
        this.flash('忽略失败：' + e.message, 5000);
      }
    },

    async refreshData() {
      this.loading = true;
      this.data = null;
      await this.triggerRssOnRefresh(true);
      await this.init();
      this.flash('🔄 已刷新');
    },

    saveToken() {
      localStorage.setItem('gh_token', this.token.trim());
      localStorage.removeItem('gh_token_type');
      this.flash('Token 已保存到本地');
      this.showSettings = false;
    },

    clearToken() {
      localStorage.removeItem('gh_token');
      localStorage.removeItem('gh_token_type');
      this.token = '';
      this.flash('Token 已清除');
    },

    // ---- 一键复制今日摘要（中文标点 + 去 markdown）----
    async loginWithGithubOAuth() {
      const clientId = String(this.oauthClientId || '').trim();
      if (!clientId) {
        this.flash('Please enter GitHub OAuth Client ID first.', 4000);
        return;
      }
      localStorage.setItem('github_oauth_client_id', clientId);
      this.oauthLoggingIn = true;
      this.oauthStatus = 'Requesting GitHub device code...';
      try {
        const tokenData = await githubDeviceLogin(clientId, (status) => { this.oauthStatus = status; });
        localStorage.setItem('gh_token', tokenData.access_token);
        localStorage.setItem('gh_token_type', 'oauth');
        localStorage.setItem('github_oauth_scope', tokenData.scope || '');
        this.token = tokenData.access_token;
        this.oauthStatus = `GitHub OAuth connected. Scope: ${tokenData.scope || 'unknown'}`;
        this.flash('GitHub OAuth login saved.', 3500);
      } catch (e) {
        this.oauthStatus = e.message || String(e);
        this.flash('GitHub OAuth login failed: ' + this.oauthStatus, 6000);
      } finally {
        this.oauthLoggingIn = false;
      }
    },

    defaultApiModels() {
      return [
        {
          label: 'DeepSeek V4 Pro',
          model: 'deepseek-v4-pro',
          base_url: 'https://api.deepseek.com',
          input_cache_hit_usd_per_million: 0.003625,
          input_cache_miss_usd_per_million: 0.435,
          output_usd_per_million: 0.87
        },
        {
          label: 'DeepSeek V4 Flash',
          model: 'deepseek-v4-flash',
          base_url: 'https://api.deepseek.com',
          input_cache_hit_usd_per_million: 0.0028,
          input_cache_miss_usd_per_million: 0.14,
          output_usd_per_million: 0.28
        }
      ];
    },

    normalizeApiModels(models) {
      const defaults = this.defaultApiModels();
      const raw = Array.isArray(models) ? models : defaults;
      const seen = new Set();
      const normalized = [];
      for (const item of raw) {
        const model = String(item?.model || '').trim();
        if (!model || seen.has(model)) continue;
        seen.add(model);
        normalized.push({
          label: String(item?.label || this.formatTranslatorModel(model) || model).trim(),
          model,
          base_url: String(item?.base_url || item?.baseUrl || this.automationConfig?.api_base_url || 'https://api.deepseek.com').trim(),
          provider: String(item?.provider || 'openai-compatible').trim(),
          input_cache_hit_usd_per_million: item?.input_cache_hit_usd_per_million ?? item?.pricing_usd_per_million?.prompt_cache_hit_tokens ?? '',
          input_cache_miss_usd_per_million: item?.input_cache_miss_usd_per_million ?? item?.pricing_usd_per_million?.prompt_cache_miss_tokens ?? '',
          output_usd_per_million: item?.output_usd_per_million ?? item?.pricing_usd_per_million?.completion_tokens ?? ''
        });
      }
      for (const item of defaults) {
        if (!seen.has(item.model)) normalized.push({ ...item, provider: 'openai-compatible' });
      }
      return normalized;
    },

    apiModelById(model) {
      const models = this.normalizeApiModels(this.automationConfig.api_models);
      return models.find(m => m.model === model) || models[0];
    },

    addApiModel() {
      const models = this.normalizeApiModels(this.automationConfig.api_models);
      models.push({
        label: '新模型',
        model: '',
        base_url: this.automationConfig.api_base_url || 'https://api.deepseek.com',
        provider: 'openai-compatible',
        input_cache_hit_usd_per_million: '',
        input_cache_miss_usd_per_million: '',
        output_usd_per_million: ''
      });
      this.automationConfig.api_models = models;
    },

    removeApiModel(index) {
      const models = Array.isArray(this.automationConfig.api_models) ? [...this.automationConfig.api_models] : this.defaultApiModels();
      if (models.length <= 1) {
        this.flash('至少保留一个模型', 2500);
        return;
      }
      models.splice(index, 1);
      this.automationConfig.api_models = models;
    },

    async loadAutomationConfig() {
      try {
        const res = await fetch('data/automation-config.json?t=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) return;
        const cfg = await res.json();
        const apiModels = this.normalizeApiModels(cfg.api_models);
        this.automationConfig = {
          title_translator: cfg.title_translator || 'openclaw',
          fulltext_translator: cfg.fulltext_translator || 'openclaw',
          nightly_learner: cfg.nightly_learner || 'openclaw',
          api_provider: cfg.api_provider || 'openai-compatible',
          api_model: cfg.api_model || 'deepseek-v4-flash',
          api_title_model: cfg.api_title_model || cfg.api_model || 'deepseek-v4-flash',
          api_fulltext_model: cfg.api_fulltext_model || 'deepseek-v4-pro',
          api_nightly_model: cfg.api_nightly_model || cfg.api_model || 'deepseek-v4-flash',
          api_title_thinking: cfg.api_title_thinking || 'disabled',
          api_fulltext_thinking: cfg.api_fulltext_thinking || 'disabled',
          api_nightly_thinking: cfg.api_nightly_thinking || 'disabled',
          api_compare_thinking: cfg.api_compare_thinking || 'disabled',
          api_base_url: cfg.api_base_url || 'https://api.deepseek.com',
          api_fulltext_batch: cfg.api_fulltext_batch || '5',
          compare_models: Array.isArray(cfg.compare_models)
            ? cfg.compare_models
            : [cfg.compare_model_a || 'deepseek-v4-pro', cfg.compare_model_b || 'deepseek-v4-flash'],
          api_models: apiModels,
          updated_at: cfg.updated_at || ''
        };
      } catch (_) {}
    },

    async saveAutomationConfig() {
      try {
        this.automationSaving = true;
        const apiModels = this.normalizeApiModels(this.automationConfig.api_models);
        const cfg = {
          title_translator: this.automationConfig.title_translator || 'openclaw',
          fulltext_translator: this.automationConfig.fulltext_translator || 'openclaw',
          nightly_learner: this.automationConfig.nightly_learner || 'openclaw',
          api_provider: 'openai-compatible',
          api_model: this.automationConfig.api_title_model || this.automationConfig.api_model || 'deepseek-v4-flash',
          api_title_model: this.automationConfig.api_title_model || this.automationConfig.api_model || 'deepseek-v4-flash',
          api_fulltext_model: this.automationConfig.api_fulltext_model || 'deepseek-v4-pro',
          api_nightly_model: this.automationConfig.api_nightly_model || this.automationConfig.api_model || 'deepseek-v4-flash',
          api_title_thinking: this.automationConfig.api_title_thinking || 'disabled',
          api_fulltext_thinking: this.automationConfig.api_fulltext_thinking || 'disabled',
          api_nightly_thinking: this.automationConfig.api_nightly_thinking || 'disabled',
          api_compare_thinking: this.automationConfig.api_compare_thinking || 'disabled',
          api_base_url: this.automationConfig.api_base_url || 'https://api.deepseek.com',
          api_fulltext_batch: this.automationConfig.api_fulltext_batch || '5',
          compare_models: this.selectedCompareModels().map(m => m.model),
          api_models: apiModels,
          updated_at: new Date().toISOString(),
          notes: 'Public switch only. API keys must stay in GitHub Actions Secrets.'
        };
        await GH.putFile(
          'data/automation-config.json',
          JSON.stringify(cfg, null, 2) + '\n',
          'chore: update automation translator switches'
        );
        this.automationConfig = cfg;
        this.flash('自动化开关已保存');
        return true;
      } catch (e) {
        this.flash('保存自动化开关失败：' + e.message, 5000);
        return false;
      } finally {
        this.automationSaving = false;
      }
    },

    apiTranslationInputs() {
      const mode = String(this.automationConfig.api_fulltext_batch || '5');
      const titleModel = this.apiModelById(this.automationConfig.api_title_model || this.automationConfig.api_model || 'deepseek-v4-flash');
      const fulltextModel = this.apiModelById(this.automationConfig.api_fulltext_model || 'deepseek-v4-pro');
      const inputs = {
        fulltext_limit: '5',
        time_budget_seconds: '1200',
        title_translator: this.automationConfig.title_translator || 'openclaw',
        fulltext_translator: this.automationConfig.fulltext_translator || 'openclaw',
        api_title_model: titleModel.model,
        api_fulltext_model: fulltextModel.model,
        api_base_url: this.automationConfig.api_base_url || 'https://api.deepseek.com',
        api_title_thinking: this.automationConfig.api_title_thinking || 'disabled',
        api_fulltext_thinking: this.automationConfig.api_fulltext_thinking || 'disabled',
        api_compare_thinking: this.automationConfig.api_compare_thinking || 'disabled',
        manual_payload: JSON.stringify({
          api_title_base_url: titleModel.base_url || this.automationConfig.api_base_url || 'https://api.deepseek.com',
          api_fulltext_base_url: fulltextModel.base_url || this.automationConfig.api_base_url || 'https://api.deepseek.com'
        })
      };
      if (mode === '10') inputs.fulltext_limit = '10';
      if (mode === 'all') {
        inputs.fulltext_limit = '999';
        inputs.time_budget_seconds = '1320';
      }
      return inputs;
    },

    apiTranslationSummary() {
      const titleApi = this.automationConfig.title_translator === 'api' || this.automationConfig.title_translator === 'deepseek';
      const fulltextApi = this.automationConfig.fulltext_translator === 'api' || this.automationConfig.fulltext_translator === 'deepseek';
      const parts = [];
      if (titleApi) parts.push(`标题/摘要：${this.formatTranslatorModel(this.automationConfig.api_title_model || this.automationConfig.api_model)}`);
      if (fulltextApi) parts.push(`正文：${this.formatTranslatorModel(this.automationConfig.api_fulltext_model)}`);
      return parts.join('，');
    },

    apiComparisonInputs(article) {
      const models = this.selectedCompareModels();
      return {
        title_translator: 'openclaw',
        fulltext_translator: 'openclaw',
        api_base_url: this.automationConfig.api_base_url || 'https://api.deepseek.com',
        manual_payload: JSON.stringify({
          compare_date: this.data?.date || this.currentDate,
          compare_article_id: String(article.id),
          compare_models: models.map(m => ({
            label: m.label || this.formatTranslatorModel(m.model),
            model: m.model,
            base_url: m.base_url || this.automationConfig.api_base_url || 'https://api.deepseek.com',
            provider: m.provider || 'openai-compatible'
          })),
          api_compare_thinking: this.automationConfig.api_compare_thinking || 'disabled'
        }),
        fulltext_limit: '5',
        time_budget_seconds: '1200'
      };
    },

    async runComparison(article) {
      if (!article || !article.id || !this.data?.date) return;
      const models = this.selectedCompareModels();
      if (models.length === 0) {
        this.flash('请先在设置里勾选参与对比的模型', 3500);
        return;
      }
      try {
        this.comparisonTriggeringId = article.id;
        await this.markComparisonRequested(article, models);
        await GH.dispatchWorkflow('api-translation.yml', this.apiComparisonInputs(article));
        this.flash(`#${article.id} 已请求多模型翻译：${models.map(m => m.label).join(' / ')}，稍后刷新查看对比`, 6500);
      } catch (e) {
        this.flash('对比翻译失败：' + e.message, 6000);
      } finally {
        this.comparisonTriggeringId = null;
      }
    },

    async markComparisonRequested(article, models) {
      const date = this.data?.date || this.currentDate;
      const indexPath = `data/${date}/index.json`;
      const fresh = await GH.getFile(indexPath);
      if (!fresh) throw new Error(`无法读取 ${indexPath}`);
      const index = JSON.parse(fresh.content);
      const target = (index.articles || []).find(a => Number(a.id) === Number(article.id));
      if (!target) throw new Error(`找不到文章 #${article.id}`);
      const now = new Date().toLocaleString('zh-CN', { hour12: false });
      target.comparison_status = 'requested';
      target.comparison_requested_at_cn = now;
      target.comparison_models = models.map(m => m.model);
      await GH.putFile(indexPath, JSON.stringify(index, null, 2) + '\n', `comparison: request #${article.id}`);
      Object.assign(article, target);
      this.data = index;
    },

    async runApiTranslationNow() {
      const titleApi = this.automationConfig.title_translator === 'api' || this.automationConfig.title_translator === 'deepseek';
      const fulltextApi = this.automationConfig.fulltext_translator === 'api' || this.automationConfig.fulltext_translator === 'deepseek';
      if (!titleApi && !fulltextApi) {
        this.flash('请先把标题/摘要或正文翻译切到 API', 3500);
        return;
      }
      try {
        this.automationTriggering = true;
        const saved = await this.saveAutomationConfig();
        if (!saved) return;
        await GH.dispatchWorkflow('api-translation.yml', this.apiTranslationInputs());
        const summary = this.apiTranslationSummary();
        this.flash(`已触发 API 翻译${summary ? '，本次使用 ' + summary : ''}，稍后刷新查看结果`, 5200);
      } catch (e) {
        this.flash('触发 API 翻译失败：' + e.message, 6000);
      } finally {
        this.automationTriggering = false;
      }
    },

    isApiMode(kind) {
      const value = this.automationConfig?.[kind];
      return value === 'api' || value === 'deepseek';
    },

    formatTranslatorModel(model) {
      const raw = String(model || '').trim();
      if (!raw) return '';
      const lower = raw.toLowerCase();
      if (lower.includes('deepseek') && lower.includes('v4') && lower.includes('pro')) return 'DeepSeek V4 Pro';
      if (lower.includes('deepseek') && lower.includes('v4') && lower.includes('flash')) return 'DeepSeek V4 Flash';
      if (lower.includes('deepseek')) return raw.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      return raw;
    },

    selectedCompareModels() {
      const selected = new Set(Array.isArray(this.automationConfig.compare_models) ? this.automationConfig.compare_models : []);
      return this.normalizeApiModels(this.automationConfig.api_models).filter(m => selected.has(m.model));
    },

    toggleCompareModel(model) {
      const current = new Set(Array.isArray(this.automationConfig.compare_models) ? this.automationConfig.compare_models : []);
      if (current.has(model)) current.delete(model);
      else current.add(model);
      this.automationConfig.compare_models = [...current];
    },

    translatorLabel(article) {
      const model = this.formatTranslatorModel(article?.translator_model);
      return model ? `由 ${model} 翻译` : '';
    },

    async triggerRssOnRefresh(force = false) {
      const token = localStorage.getItem('gh_token');
      if (!token || this.rssTriggering) return false;
      const key = 'ign_daily_last_rss_dispatch_at';
      const now = Date.now();
      const last = Number(localStorage.getItem(key) || 0);
      const cooldownMs = 10 * 60 * 1000;
      if (!force && now - last < cooldownMs) return false;
      try {
        this.rssTriggering = true;
        await GH.dispatchWorkflow('hourly-rss.yml');
        localStorage.setItem(key, String(now));
        return true;
      } catch (_) {
        return false;
      } finally {
        this.rssTriggering = false;
      }
    },

    normalizePunctuation(text) {
      if (!text) return '';
      let s = String(text);
      // 1. 去 HTML/markdown 标记
      s = s.replace(/<[^>]+>/g, '');
      s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');         // [text](url)
      s = s.replace(/\*\*([^*]+)\*\*/g, '$1');                 // **bold**
      s = s.replace(/__([^_]+)__/g, '$1');                     // __bold__
      s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '$1');     // *italic*
      s = s.replace(/(?<!_)_([^_\n]+)_(?!_)/g, '$1');          // _italic_
      s = s.replace(/`([^`]+)`/g, '$1');                       // `code`
      s = s.replace(/^\s{0,3}#{1,6}\s+/gm, '');                // # heading
      s = s.replace(/^\s{0,3}>\s+/gm, '');                     // > quote
      s = s.replace(/^\s{0,3}[-*+]\s+/gm, '');                 // - list
      s = s.replace(/^\s{0,3}\d+\.\s+/gm, '');                 // 1. list
      // 2. 上下文感知 ASCII → 全角
      const CJK = '[\u4e00-\u9fff]';
      s = s.replace(new RegExp(`(${CJK})\\s*,\\s*(${CJK}|$|\\n)`, 'g'), '$1，$2');
      s = s.replace(new RegExp(`(${CJK}|^|\\n)\\s*,\\s*(${CJK})`, 'g'), '$1，$2');
      s = s.replace(new RegExp(`(${CJK})\\s*\\.\\s*(${CJK}|$|\\n)`, 'g'), '$1。$2');
      s = s.replace(new RegExp(`(${CJK})\\.(\\s|$)`, 'g'), '$1。$2');
      s = s.replace(new RegExp(`(${CJK})\\s*\\?\\s*`, 'g'), '$1？');
      s = s.replace(new RegExp(`(${CJK})\\s*!\\s*`, 'g'), '$1！');
      s = s.replace(new RegExp(`(${CJK})\\s*:\\s*(${CJK}|$|\\n|\\s)`, 'g'), '$1：$2');
      s = s.replace(new RegExp(`(${CJK})\\s*;\\s*`, 'g'), '$1；');
      // 含 CJK 的括号 → 全角
      s = s.replace(/\(([^()]*[\u4e00-\u9fff][^()]*)\)/g, '（$1）');
      // 全角双引号 + ASCII 双引号 交替换 「」
      let open = true;
      s = s.replace(/["“”]/g, () => {
        const c = open ? '「' : '」';
        open = !open;
        return c;
      });
      // 3. 多余空格
      s = s.replace(/[ \t]+\n/g, '\n');
      s = s.replace(/\n{3,}/g, '\n\n');
      let prev;
      do {
        prev = s;
        s = s.replace(/([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g, '$1$2');
      } while (s !== prev);
      s = s.replace(/\s+([\u3000-\u303f\uff00-\uffef\u300c\u300d\u300e\u300f])/g, '$1');
      s = s.replace(/([\u3000-\u303f\uff00-\uffef\u300c\u300d\u300e\u300f])\s+/g, '$1');
      return s.trim();
    },

    exportBasketStorageKey() {
      return 'ign_daily_export_basket_v1';
    },

    loadExportBasket() {
      try {
        const raw = localStorage.getItem(this.exportBasketStorageKey());
        const items = raw ? JSON.parse(raw) : [];
        this.exportBasket = Array.isArray(items) ? items : [];
      } catch (_) {
        this.exportBasket = [];
      }
    },

    saveExportBasket() {
      localStorage.setItem(this.exportBasketStorageKey(), JSON.stringify(this.exportBasket));
    },

    selectedArticleObjects() {
      if (!this.data?.articles?.length || !this.selected.length) return [];
      const ids = new Set(this.selected.map(x => Number(x)));
      return this.data.articles.filter(a => ids.has(Number(a.id)));
    },

    normalizeExportArticle(article, date = this.data?.date || this.currentDate) {
      const enTitle = (article.en_title || article.title || '').trim();
      const rawCnTitle = (article.cn_title || '').trim();
      const cnTitle = rawCnTitle && rawCnTitle !== enTitle ? this.normalizePunctuation(rawCnTitle) : '';
      return {
        key: `${date}#${article.id}`,
        date,
        id: Number(article.id),
        en_title: enTitle,
        cn_title: cnTitle,
        category: (article.category || '未分类').trim(),
        publish_time_cn: article.publish_time_cn || article.pub_date || article.pubDate_cst || '',
        summary: this.normalizePunctuation(article.summary || ''),
        url: article.url || ''
      };
    },

    addSelectedToExportBasket() {
      const articles = this.selectedArticleObjects().map(a => this.normalizeExportArticle(a));
      if (!articles.length) {
        this.flash('请先勾选要导出的文章', 2500);
        return;
      }
      const merged = new Map(this.exportBasket.map(a => [a.key, a]));
      for (const article of articles) merged.set(article.key, article);
      this.exportBasket = Array.from(merged.values()).sort((a, b) => this.compareExportArticles(a, b));
      this.saveExportBasket();
      this.flash(`已加入导出篮：${articles.length} 篇`);
    },

    clearExportBasket() {
      this.exportBasket = [];
      this.saveExportBasket();
      this.flash('导出篮已清空');
    },

    compareExportArticles(a, b) {
      const ad = `${a.date || ''} ${a.publish_time_cn || ''}`;
      const bd = `${b.date || ''} ${b.publish_time_cn || ''}`;
      return bd.localeCompare(ad) || Number(a.id || 0) - Number(b.id || 0);
    },

    exportExcelDateLabel(date) {
      const m = String(date || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
      return m ? `${m[1]}年${m[2]}月${m[3]}日` : String(date || '多日期');
    },

    exportExcelFilename(articles) {
      const dates = Array.from(new Set(articles.map(a => a.date).filter(Boolean))).sort();
      if (dates.length === 1) return `${this.exportExcelDateLabel(dates[0])}IGN翻译精选.xlsx`;
      const first = dates[0] || this.currentDate;
      const last = dates[dates.length - 1] || this.currentDate;
      return `IGN翻译精选_${first}_至_${last}.xlsx`;
    },

    exportExcelSheetName(articles) {
      const dates = Array.from(new Set(articles.map(a => a.date).filter(Boolean)));
      const name = dates.length === 1
        ? `IGN翻译精选${this.exportExcelDateLabel(dates[0])}`
        : 'IGN翻译精选多日期';
      return name.replace(/[*?:\\/[\]]/g, '').slice(0, 31) || 'IGN Daily';
    },

    async exportSelectedExcel() {
      const merged = new Map(this.exportBasket.map(a => [a.key, a]));
      for (const article of this.selectedArticleObjects().map(a => this.normalizeExportArticle(a))) {
        merged.set(article.key, article);
      }
      const articles = Array.from(merged.values()).sort((a, b) => this.compareExportArticles(a, b));
      if (!articles.length) {
        this.flash('请先勾选文章，或先加入导出篮', 3000);
        return;
      }
      if (!window.ExcelJS) {
        this.flash('Excel 导出库未加载，请刷新页面后重试', 4000);
        return;
      }

      try {
        const workbook = new ExcelJS.Workbook();
        workbook.creator = 'IGN Daily';
        workbook.created = new Date();
        const sheet = workbook.addWorksheet(this.exportExcelSheetName(articles));
        sheet.columns = [
          { header: '#', key: 'no', width: 6 },
          { header: '英文标题', key: 'en_title', width: 50 },
          { header: '中文标题', key: 'cn_title', width: 30 },
          { header: '分类', key: 'category', width: 12 },
          { header: '发布时间(北京)', key: 'publish_time_cn', width: 18 },
          { header: '摘要', key: 'summary', width: 60 },
          { header: '链接', key: 'url', width: 60 }
        ];
        sheet.views = [{ state: 'frozen', ySplit: 1 }];
        sheet.autoFilter = 'A1:G1';

        const header = sheet.getRow(1);
        header.height = 24;
        header.font = { bold: true, color: { argb: 'FFFFFFFF' } };
        header.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F2937' } };
        header.alignment = { vertical: 'middle', horizontal: 'center', wrapText: true };

        articles.forEach((article, index) => {
          const row = sheet.addRow({
            no: index + 1,
            en_title: article.en_title,
            cn_title: article.cn_title,
            category: article.category,
            publish_time_cn: article.publish_time_cn,
            summary: article.summary,
            url: article.url
          });
          row.height = 35;
          row.alignment = { vertical: 'top', wrapText: true };
          row.getCell(1).alignment = { vertical: 'middle', horizontal: 'center' };
          const linkCell = row.getCell(7);
          if (article.url) {
            linkCell.value = { text: article.url, hyperlink: article.url };
            linkCell.font = { color: { argb: 'FF2563EB' }, underline: true };
          }
        });

        sheet.eachRow(row => {
          row.eachCell(cell => {
            cell.border = {
              top: { style: 'thin', color: { argb: 'FFE5E7EB' } },
              left: { style: 'thin', color: { argb: 'FFE5E7EB' } },
              bottom: { style: 'thin', color: { argb: 'FFE5E7EB' } },
              right: { style: 'thin', color: { argb: 'FFE5E7EB' } }
            };
          });
        });

        const buffer = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buffer], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = this.exportExcelFilename(articles);
        document.body.appendChild(link);
        link.click();
        URL.revokeObjectURL(link.href);
        document.body.removeChild(link);
        this.flash(`已导出 ${articles.length} 篇文章`);
      } catch (e) {
        this.flash('Excel 导出失败：' + e.message, 5000);
      }
    },

    async copyDigest() {
      if (!this.data || !this.data.articles?.length) {
        this.flash('⚠️ 今日暂无文章', 2000);
        return;
      }
      // 如果选中了部分则只复制选中的，否则复制全部
      const sel = this.selected && this.selected.length > 0
        ? new Set(this.selected.map(x => Number(x)))
        : null;
      const articles = this.data.articles.filter(a => !sel || sel.has(a.id));

      const lines = [];
      lines.push(`📰 IGN Daily News | ${this.data.date}`);
      lines.push(`共 ${articles.length} 条${sel ? '（已选）' : ''}`);
      lines.push('');
      articles.forEach((a, i) => {
        const idx = i + 1;
        const emoji = a.emoji || '📰';
        const enT = (a.en_title || '').trim();
        const cnT = this.normalizePunctuation(a.cn_title || '');
        const sumT = this.normalizePunctuation(a.summary || '');
        lines.push(`${idx}. ${emoji} ${enT}（${cnT}）`);
        if (sumT) lines.push(sumT);
        lines.push('');
      });
      const out = lines.join('\n').trim();

      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(out);
        } else {
          const ta = document.createElement('textarea');
          ta.value = out;
          ta.style.position = 'fixed'; ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }
        this.copyBtnText = '✅ 已复制';
        setTimeout(() => { this.copyBtnText = '📋 复制摘要'; }, 2000);
      } catch (e) {
        this.flash('❌ 复制失败：' + e.message, 3000);
      }
    },

    async submitRequest() {
      if (this.selected.length === 0) return;
      try {
        const date = this.data.date;
        const selIds = [...this.selected].map(x => Number(x)).sort((a,b) => a-b);
        // Build URL map so heartbeat can match by URL even if IDs shift
        const requested_articles = selIds.map(id => {
          const art = this.data.articles.find(a => a.id === id);
          return art ? {
            id,
            url: art.url,
            en_title: art.en_title,
            cn_title: art.cn_title,
            publish_time_cn: art.publish_time_cn || art.pub_date || art.pubDate_cst || ''
          } : { id };
        });
        const payload = {
          date,
          requested_ids: selIds,
          requested_articles,
          requested_at: new Date().toISOString()
        };
        const path = `data/${date}/requests.json`;
        await GH.putFile(path, JSON.stringify(payload, null, 2),
          `request translation for ${date}: ${payload.requested_ids.join(',')}`);
        await this.clearSelectedTranslationFailures(date, selIds);
        const apiFulltext = this.isApiMode('fulltext_translator');
        if (apiFulltext) {
          await this.saveAutomationConfig();
          await GH.dispatchWorkflow('api-translation.yml', this.apiTranslationInputs());
          const summary = this.apiTranslationSummary();
          this.flash(`✅ 已请求翻译 ${this.selected.length} 篇，API Actions 已开始处理${summary ? '，本次使用 ' + summary : ''}`);
        } else {
          this.flash(`✅ 已请求翻译 ${this.selected.length} 篇，OpenClaw 会处理`);
        }
        // 标记 requested
        for (const id of this.selected) {
          const a = this.data.articles.find(x => x.id === id);
          if (a && a.translation_status !== 'done') a.translation_status = 'requested';
        }
        this.selected = [];
      } catch (e) {
        this.flash('❌ 提交失败：' + e.message, 4000);
      }
    },

    async clearSelectedTranslationFailures(date, ids) {
      if (!ids?.length) return;
      const failPath = `data/${date}/translation_failures.json`;
      try {
        const fresh = await GH.getFile(failPath);
        if (!fresh) return;
        const data = JSON.parse(fresh.content);
        const items = data.items || {};
        let changed = false;
        for (const id of ids) {
          if (items[String(id)]) {
            delete items[String(id)];
            changed = true;
          }
        }
        if (!changed) return;
        data.items = items;
        data.updated_at = new Date().toISOString();
        await GH.putFile(failPath, JSON.stringify(data, null, 2), `translation failures: retry ${ids.join(',')}`);
      } catch (_) {
        // 失败记录只是显示层，不能阻断提交翻译。
      }
    },

    flash(msg, ms = 2500) {
      this.toast = msg;
      setTimeout(() => { this.toast = ''; }, ms);
    },

    // ---- 主题 ----
    toggleTheme() {
      const next = window.appTheme.toggleTheme();
      this.themeIcon = next === 'dark' ? '☀️' : (next === 'light' ? '🌒' : '🌗');
      this.flash('主题：' + (next === 'auto' ? '跟随系统' : (next === 'dark' ? '深色' : '浅色')));
    },

    // ---- 全局搜索 ----
    runGlobalSearch() {
      clearTimeout(this.searchTimer);
      const q = this.searchQuery.trim().toLowerCase();
      if (!q) { this.searchResults = []; return; }
      this.searchLoading = true;
      this.searchTimer = setTimeout(async () => {
        try {
          // 首次加载历史总索引
          if (!this.searchCache) {
            const histRes = await fetch('data/index-list.json?t=' + Date.now());
            const hist = histRes.ok ? await histRes.json() : [];
            // 只扫近 14 天
            const recent = hist.slice(0, 14);
            const pages = await Promise.all(recent.map(async (d) => {
              try {
                const r = await fetch(`data/${d.date}/index.json?t=${Date.now()}`);
                if (!r.ok) return [];
                const j = await r.json();
                return j.articles.map(a => ({ ...a, date: d.date }));
              } catch (_) { return []; }
            }));
            this.searchCache = pages.flat();
          }
          // 在总索引里模糊q查 cn_title/en_title/summary/category
          const results = [];
          for (const a of this.searchCache) {
            const fields = [a.cn_title, a.en_title, a.summary || '', a.category || ''].join(' ・ ').toLowerCase();
            if (fields.includes(q)) {
              results.push({
                date: a.date, id: a.id, cn_title: a.cn_title, en_title: a.en_title,
                category: a.category, matchedSnippet: ''
              });
            }
          }
          this.searchResults = results.slice(0, 50);
        } catch (e) {
          console.error(e);
        } finally {
          this.searchLoading = false;
        }
      }, 200);
    },

    highlightMatch(text) {
      if (!text) return '';
      const q = this.searchQuery.trim();
      if (!q) return this.escapeHtml(text);
      const safe = this.escapeHtml(text);
      const re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      return safe.replace(re, '<mark class="bg-amber-200">$1</mark>');
    },
    escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    },

    // ---- 全局待确认词库 ----
    async loadGlobalPending() {
      if (!this.data) return;
      const pending = [];
      const translated = this.data.articles.filter(a => a.translation_status === 'done');
      // 并发拉取所有译文
      await Promise.all(translated.map(async (a) => {
        const padded = String(a.id).padStart(2, '0');
        try {
          const res = await fetch(`data/${this.data.date}/translations/${padded}.json?t=${Date.now()}`);
          if (!res.ok) return;
          const tr = await res.json();
          if (Array.isArray(tr.pending_dict) && tr.pending_dict.length > 0) {
            for (const c of tr.pending_dict) {
              pending.push({
                ...c,
                _articleId: a.id,
                _articleTitle: a.cn_title.length > 16 ? a.cn_title.slice(0,16)+'…' : a.cn_title
              });
            }
          }
        } catch (_) {}
      }));
      this.globalPending = pending;
    },

    approveGlobalPending(idx) {
      const c = this.globalPending[idx];
      if (!c.en || !c.cn) {
        this.flash('❌ 译名不能为空', 3000);
        return;
      }
      if (!localStorage.getItem('gh_token')) {
        this.flash('❌ 未配置 GitHub Token，请右上角⚙️设置', 4000);
        return;
      }
      const candidate = { ...c };
      this.globalPending.splice(idx, 1);
      this.flash(`入库中: ${candidate.en} → ${candidate.cn}`);
      this.pendingQueue.push({ type: 'approve', candidate });
      this.processGlobalQueue();
    },

    ignoreGlobalPending(idx) {
      const c = this.globalPending[idx];
      this.globalPending.splice(idx, 1);
      if (!localStorage.getItem('gh_token')) return;
      this.pendingQueue.push({ type: 'ignore', candidate: c });
      this.processGlobalQueue();
    },

    approveAllGlobal() {
      if (!localStorage.getItem('gh_token')) {
        this.flash('❌ 未配置 GitHub Token', 4000);
        return;
      }
      const candidates = this.globalPending.filter(c => c.en && c.cn).map(c => ({ ...c }));
      this.globalPending = [];
      this.flash(`入库中: ${candidates.length} 条...`);
      for (const c of candidates) this.pendingQueue.push({ type: 'approve', candidate: c });
      this.processGlobalQueue();
    },

    ignoreAllGlobal() {
      const all = [...this.globalPending];
      this.globalPending = [];
      if (!localStorage.getItem('gh_token')) return;
      for (const c of all) this.pendingQueue.push({ type: 'ignore', candidate: c });
      this.processGlobalQueue();
    },

    async processGlobalQueue() {
      if (this.pendingProcessing) return;
      this.pendingProcessing = true;
      try {
        while (this.pendingQueue.length > 0) {
          // 批量拿出队列里全部任务
          const batch = this.pendingQueue.splice(0, this.pendingQueue.length);
          const approves = batch.filter(x => x.type === 'approve').map(x => x.candidate);
          // 1. 批量入库
          if (approves.length > 0) {
            await this.batchApproveDict(approves);
          }
          // 2. 按文章分组更新各自的 pending_dict
          const byArticle = {};
          for (const item of batch) {
            const aid = item.candidate._articleId;
            if (!byArticle[aid]) byArticle[aid] = [];
            byArticle[aid].push(item.candidate);
          }
          for (const [aid, removed] of Object.entries(byArticle)) {
            await this.removeFromArticlePending(parseInt(aid), removed);
          }
        }
        if (this.globalPending.length === 0) {
          this.flash('✅ 全部处理完成');
        }
      } catch (e) {
        this.flash('❌ 后台保存失败：' + e.message, 5000);
      } finally {
        this.pendingProcessing = false;
      }
    },

    async batchApproveDict(approves) {
      const fresh = await GH.getFile('data/dict.json');
      const dict = JSON.parse(fresh.content);
      for (const c of approves) {
        for (const cat of ['games','movies_tv','companies','people','media','terms']) {
          if (cat !== c.cat && dict[cat]?.[c.en]) delete dict[cat][c.en];
        }
        if (!dict[c.cat]) dict[c.cat] = {};
        dict[c.cat][c.en] = { cn: c.cn, source: c.source };
      }
      dict._meta = dict._meta || {};
      dict._meta.last_updated = new Date().toISOString().slice(0,10);
      const msg = approves.length === 1
        ? `dict: approve ${approves[0].en} → ${approves[0].cn}`
        : `dict: approve ${approves.length} entries (global panel)`;
      await GH.putFile('data/dict.json', JSON.stringify(dict, null, 2), msg);
    },

    async removeFromArticlePending(articleId, removedCandidates) {
      const padded = String(articleId).padStart(2, '0');
      const path = `data/${this.data.date}/translations/${padded}.json`;
      const fresh = await GH.getFile(path);
      const data = JSON.parse(fresh.content);
      // 从 pending_dict 里移除这些候选（按 en+cat 匹配）
      const removeSet = new Set(removedCandidates.map(c => `${c.en}|${c.cat}`));
      data.pending_dict = (data.pending_dict || []).filter(
        c => !removeSet.has(`${c.en}|${c.cat}`)
      );

      // ✨ 新：即时替换段落里的译文
      let replacedCount = 0;
      const replacements = [];
      for (const c of removedCandidates) {
        // 只处理被批准的（有 cn 且 en !== cn）
        if (!c.cn || c.cn === c.en) continue;
        replacements.push({ en: c.en, cn: c.cn });
      }
      // 按长度降序，避免短名覆盖长名的一部分
      replacements.sort((a, b) => b.en.length - a.en.length);

      if (replacements.length > 0 && Array.isArray(data.paragraphs)) {
        for (const para of data.paragraphs) {
          if (!para.cn) continue;
          const before = para.cn;
          for (const r of replacements) {
            // 只替换 cn 里还是原英文的地方，避免中文已绑定的文本被重复覆写
            // 用不能是单词边界（中文没有 \b），用 split-join 避免 regex 转义
            para.cn = para.cn.split(r.en).join(r.cn);
          }
          if (para.cn !== before) replacedCount++;
        }
        // 同时替换标题和摘要
        if (data.cn_title) {
          for (const r of replacements) data.cn_title = data.cn_title.split(r.en).join(r.cn);
        }
        if (data.summary) {
          for (const r of replacements) data.summary = data.summary.split(r.en).join(r.cn);
        }
      }

      const msg = replacedCount > 0
        ? `pending_dict: applied ${replacements.length} terms in #${articleId} (${replacedCount} paragraphs)`
        : `pending_dict: clear processed for #${articleId}`;
      await GH.putFile(path, JSON.stringify(data, null, 2), msg);
    },
  };
}

// ---- PWA Service Worker Registration ----
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/ign-daily/sw.js')
      .then((reg) => console.log('SW registered:', reg.scope))
      .catch((err) => console.warn('SW registration failed:', err));
  });
}
