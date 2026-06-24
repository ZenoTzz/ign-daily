const api = require('../../utils/api');
const { todayNewsDate, shiftDate } = require('../../utils/date');

function statusLabel(status) {
  if (status === 'done') return '已完成';
  if (status === 'requested') return '翻译中';
  if (status === 'needs_review') return '需复核';
  return '待选择';
}

function statusClass(status) {
  if (status === 'done') return 'status-done';
  if (status === 'requested') return 'status-requested';
  if (status === 'needs_review') return 'status-review';
  return '';
}

Page({
  data: {
    date: todayNewsDate(),
    articles: [],
    selectedIds: [],
    submitText: '提交翻译',
    pendingCount: 0,
    requestedCount: 0,
    doneCount: 0,
    loading: false,
    submitting: false,
    error: '',
    job: null,
    jobLabel: '',
    jobIdsText: '',
    jobTimer: null
  },

  async onLoad() {
    if (!api.token()) {
      wx.redirectTo({ url: '/pages/login/login' });
      return;
    }
    await this.restoreJob();
    await this.loadData();
  },

  onUnload() {
    this.clearJobTimer();
  },

  onPullDownRefresh() {
    this.loadData().finally(() => wx.stopPullDownRefresh());
  },

  noop() {},

  async loadData() {
    this.setData({ loading: true, error: '' });
    try {
      await api.me();
      const data = await api.articles(this.data.date);
      const selected = new Set(this.data.selectedIds.map(Number));
      const articles = (data.articles || []).map((item) => {
        const status = item.translation_status || 'none';
        const isDone = status === 'done';
        const isSelected = selected.has(Number(item.id));
        return Object.assign({}, item, {
          selected: isSelected,
          cover_image: item.cover_image || (item.images && item.images[0]) || '',
          status_label: statusLabel(status),
          status_class: statusClass(status),
          select_disabled: isDone,
          select_label: isDone ? '完成' : (isSelected ? '已选' : '选择')
        });
      });
      this.setData({
        articles,
        pendingCount: articles.filter((a) => !['done', 'requested', 'needs_review'].includes(a.translation_status)).length,
        requestedCount: articles.filter((a) => a.translation_status === 'requested').length,
        doneCount: articles.filter((a) => a.translation_status === 'done').length
      });
    } catch (err) {
      if (err.statusCode === 401) {
        wx.removeStorageSync('ign_token');
        wx.redirectTo({ url: '/pages/login/login' });
        return;
      }
      this.setData({ error: err.message || '加载失败' });
    } finally {
      this.setData({ loading: false });
    }
  },

  toggleSelect(e) {
    const id = Number(e.currentTarget.dataset.id);
    const article = this.data.articles.find((item) => Number(item.id) === id);
    if (!article || article.translation_status === 'done') return;
    const current = new Set(this.data.selectedIds.map(Number));
    if (current.has(id)) current.delete(id);
    else current.add(id);
    const selectedIds = Array.from(current).sort((a, b) => a - b);
    const selected = new Set(selectedIds);
    this.setData({
      selectedIds,
      submitText: selectedIds.length ? `提交翻译 (${selectedIds.length})` : '提交翻译',
      articles: this.data.articles.map((item) => {
        const isSelected = selected.has(Number(item.id));
        return Object.assign({}, item, {
          selected: isSelected,
          select_label: item.select_disabled ? '完成' : (isSelected ? '已选' : '选择')
        });
      })
    });
  },

  async submitSelected() {
    if (!this.data.selectedIds.length) return;
    this.setData({ submitting: true });
    try {
      const res = await api.requestTranslation(this.data.date, this.data.selectedIds);
      if (res.job_id) {
        wx.setStorageSync('ign_job_id', res.job_id);
        await this.loadJob(res.job_id, true);
      }
      wx.showToast({ title: '已提交翻译', icon: 'success' });
      this.setData({ selectedIds: [], submitText: '提交翻译' });
      await this.loadData();
    } catch (err) {
      wx.showToast({ title: err.message || '提交失败', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async restoreJob() {
    const saved = wx.getStorageSync('ign_job_id');
    if (saved) {
      await this.loadJob(saved, true);
      return;
    }
    try {
      const res = await api.jobs();
      const latest = (res.jobs || []).find((item) => ['queued', 'running'].includes(item.status));
      if (latest) {
        wx.setStorageSync('ign_job_id', latest.id);
        await this.loadJob(latest.id, true);
      }
    } catch (_) {}
  },

  async loadJob(jobId, startTimer) {
    try {
      const res = await api.job(jobId);
      const job = res.job;
      const jobLabel = job.status === 'done' ? '翻译完成' : job.status === 'failed' ? '翻译失败' : (job.message || '正在翻译');
      this.setData({
        job,
        jobLabel,
        jobIdsText: (job.ids || []).join(', #')
      });
      if (job.status === 'done' || job.status === 'failed') {
        wx.removeStorageSync('ign_job_id');
        this.clearJobTimer();
        if (job.status === 'done') this.loadData();
        return;
      }
      if (startTimer && !this.data.jobTimer) {
        const timer = setInterval(() => this.loadJob(jobId, false), 5000);
        this.setData({ jobTimer: timer });
      }
    } catch (_) {
      this.clearJobTimer();
    }
  },

  clearJobTimer() {
    if (this.data.jobTimer) {
      clearInterval(this.data.jobTimer);
      this.setData({ jobTimer: null });
    }
  },

  openArticle(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/article/article?date=${this.data.date}&id=${id}` });
  },

  prevDate() {
    this.setData({ date: shiftDate(this.data.date, -1), selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  nextDate() {
    this.setData({ date: shiftDate(this.data.date, 1), selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  today() {
    this.setData({ date: todayNewsDate(), selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  logout() {
    wx.removeStorageSync('ign_token');
    wx.redirectTo({ url: '/pages/login/login' });
  }
});
