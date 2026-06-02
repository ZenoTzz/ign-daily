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

  async getFile(path) {
    const url = `${this.apiBase}/repos/${this.owner}/${this.repo}/contents/${path}?ref=${this.branch}&t=${Date.now()}`;
    const token = localStorage.getItem('gh_token') || '';
    const headers = {};
    if (token) headers.Authorization = `token ${token}`;
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
        Authorization: `token ${token}`,
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
        Authorization: `token ${token}`,
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
        Authorization: `token ${token}`,
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

// ---- Today helpers ----
function todayBeijingDate() {
  // 北京时间 YYYY-MM-DD
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const beijing = new Date(utc + 8 * 3600 * 1000);
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
    showDatePicker: false,
    showMobileMenu: false,
    selected: [],
    copyBtnText: '📋 复制摘要',
    filterCat: 'all',
    showSettings: false,
    token: localStorage.getItem('gh_token') || '',
    automationConfig: {
      title_translator: 'openclaw',
      fulltext_translator: 'openclaw',
      nightly_learner: 'openclaw',
      api_provider: 'openai-compatible',
      api_model: 'deepseek-v4-flash',
      api_title_model: 'deepseek-v4-flash',
      api_fulltext_model: 'deepseek-v4-pro',
      api_nightly_model: 'deepseek-v4-flash',
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
            this.availableDates = (Array.isArray(il) ? il.map(x => x.date || x) : (il.dates || [])).sort().reverse();
          }
        } catch (_) {}
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

        // 同步 requests.json：把已请求但还没翻译的标记为 requested
        try {
          const reqRes = await fetch(`data/${date}/requests.json?t=${Date.now()}`, { cache: 'no-store' });
          if (reqRes.ok) {
            const reqData = await reqRes.json();
            const requested = new Set(reqData.requested_ids || []);
            const requestedUrls = new Set((reqData.requested_articles || []).map(x => x.url).filter(Boolean));
            for (const a of this.data.articles) {
              if ((requestedUrls.has(a.url) || requested.has(a.id)) && a.translation_status !== 'done') {
                a.translation_status = 'requested';
              }
            }
          }
        } catch (_) { /* 没有 requests.json 是正常的 */ }

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

    async refreshData() {
      this.loading = true;
      this.data = null;
      await this.triggerRssOnRefresh(true);
      await this.init();
      this.flash('🔄 已刷新');
    },

    saveToken() {
      localStorage.setItem('gh_token', this.token.trim());
      this.flash('Token 已保存到本地');
      this.showSettings = false;
    },

    clearToken() {
      localStorage.removeItem('gh_token');
      this.token = '';
      this.flash('Token 已清除');
    },

    // ---- 一键复制今日摘要（中文标点 + 去 markdown）----
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
          }))
        }),
        fulltext_limit: '5',
        time_budget_seconds: '1200'
      };
    },

    async runComparison(article) {
      if (!article || !article.id || !this.data?.date) return;
      const models = this.selectedCompareModels();
      if (models.length === 0) {
        this.flash('请至少选择一个模型再翻译对比', 3500);
        return;
      }
      try {
        this.comparisonTriggeringId = article.id;
        await GH.dispatchWorkflow('api-translation.yml', this.apiComparisonInputs(article));
        article.comparison_status = 'requested';
        this.flash(`已触发 #${article.id} 多模型翻译：${models.map(m => m.label).join(' / ')}`, 6000);
      } catch (e) {
        this.flash('触发对比翻译失败：' + e.message, 6000);
      } finally {
        this.comparisonTriggeringId = null;
      }
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
          if (a && a.translation_status === 'none') a.translation_status = 'requested';
        }
        this.selected = [];
      } catch (e) {
        this.flash('❌ 提交失败：' + e.message, 4000);
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
