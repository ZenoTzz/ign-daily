// ign-daily / app.js

// ---- GitHub API helper (用于写回) ----
const GH = {
  owner: 'ZenoTzz',
  repo: 'ign-daily',
  branch: 'main',
  apiBase: 'https://api.github.com',

  async getFile(path) {
    const url = `${this.apiBase}/repos/${this.owner}/${this.repo}/contents/${path}?ref=${this.branch}`;
    const token = localStorage.getItem('gh_token') || '';
    const res = await fetch(url, {
      headers: token ? { Authorization: `token ${token}` } : {}
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
    const data = await res.json();
    return {
      sha: data.sha,
      content: decodeURIComponent(escape(atob(data.content)))
    };
  },

  async putFile(path, content, message) {
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

    async init() {
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
        this.loading = false;
      } catch (e) {
        console.error(e);
        this.error = '加载失败：' + e.message;
        this.loading = false;
      }
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
          requested_ids: [...this.selected].sort((a,b) => a-b),
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
    }
  };
}
