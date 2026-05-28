// ign-daily / app.js

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
    selected: [],
    filterCat: 'all',
    showSettings: false,
    token: localStorage.getItem('gh_token') || '',
    toast: '',

    // 全局待确认词库
    globalPending: [],
    showPendingPanel: false,
    pendingQueue: [],
    pendingProcessing: false,

    async init() {
      // 马上绑 beforeunload 保护
      window.addEventListener('beforeunload', (e) => {
        if (this.pendingProcessing || this.pendingQueue.length > 0) {
          e.preventDefault();
          e.returnValue = '后台还有未保存的词库修改，确定要离开吗？';
          return e.returnValue;
        }
      });
      try {
        const date = new URLSearchParams(location.search).get('date') || todayBeijingDate();
        const res = await fetch(`data/${date}/index.json?t=${Date.now()}`);
        if (!res.ok) {
          // 找不到今日，回退尝试最近一天
          this.error = `${date} 还没有数据，请等待早晨8:30的cron推送，或访问 历史 页面查看过往内容。`;
          this.loading = false;
          return;
        }
        this.data = await res.json();

        // 同步 requests.json：把已请求但还没翻译的标记为 requested
        try {
          const reqRes = await fetch(`data/${date}/requests.json?t=${Date.now()}`);
          if (reqRes.ok) {
            const reqData = await reqRes.json();
            const requested = new Set(reqData.requested_ids || []);
            for (const a of this.data.articles) {
              if (requested.has(a.id) && a.translation_status !== 'done') {
                a.translation_status = 'requested';
              }
            }
          }
        } catch (_) { /* 没有 requests.json 是正常的 */ }

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
      return this.data.articles.filter(a => a.category === this.filterCat);
    },

    get translatedCount() {
      if (!this.data) return 0;
      return this.data.articles.filter(a => a.translation_status === 'done').length;
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

    async submitRequest() {
      if (this.selected.length === 0) return;
      try {
        const date = this.data.date;
        const payload = {
          date,
          requested_ids: [...this.selected].map(x => Number(x)).sort((a,b) => a-b),
          requested_at: new Date().toISOString()
        };
        const path = `data/${date}/requests.json`;
        await GH.putFile(path, JSON.stringify(payload, null, 2),
          `request translation for ${date}: ${payload.requested_ids.join(',')}`);
        this.flash(`✅ 已请求翻译 ${this.selected.length} 篇，主session会处理`);
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
      await GH.putFile(path, JSON.stringify(data, null, 2),
        `pending_dict: clear processed for #${articleId}`);
    }
  };
}
