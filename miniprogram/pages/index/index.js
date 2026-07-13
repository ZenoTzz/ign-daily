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

function nextTranslationWindowLabel(now = new Date()) {
  const beijing = new Date(now.getTime() + 8 * 3600 * 1000);
  const minutes = beijing.getUTCHours() * 60 + beijing.getUTCMinutes();
  const nextMinutes = (Math.floor(minutes / 120) + 1) * 120;
  const nextDay = nextMinutes >= 1440;
  const hour = Math.floor((nextMinutes % 1440) / 60);
  return `${nextDay ? '明天' : '今天'} ${String(hour).padStart(2, '0')}:00`;
}

Page({
  data: {
    date: todayNewsDate(),
    articles: [],
    visibleArticles: [],
    filter: 'all',
    filters: [
      { key:'all', label:'全部' }, { key:'pending', label:'待选' },
      { key:'requested', label:'翻译中' }, { key:'needs_review', label:'待复核' }, { key:'done', label:'已完成' }
    ],
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
    ,todayDate: todayNewsDate(), latestDate: '', availableDates: [], isToday: true,
    nextTranslationWindow: nextTranslationWindowLabel()
  },

  async onLoad() {
    if (!api.token()) {
      wx.redirectTo({ url: '/pages/login/login' });
      return;
    }
    await this.resolveInitialDate();
    await this.restoreJob();
    await this.loadData();
  },

  onShow() {
    if (!api.token()) return;
    this.setData({ nextTranslationWindow: nextTranslationWindowLabel() });
    const targetDate = wx.getStorageSync('ign_target_date');
    if (targetDate) {
      wx.removeStorageSync('ign_target_date');
      this.setData({ date: targetDate, selectedIds: [], submitText: '提交翻译' });
      this.loadData();
    }
  },

  onUnload() {
    this.clearJobTimer();
  },

  onPullDownRefresh() {
    this.loadData().finally(() => wx.stopPullDownRefresh());
  },

  noop() {},

  async resolveInitialDate() {
    try {
      const result = await api.dates();
      const latestDate = result.latest || '';
      if (!latestDate) return;
      const date = (result.dates || []).includes(this.data.date) ? this.data.date : latestDate;
      this.setData({ date, latestDate, availableDates: result.dates || [], todayDate: latestDate, isToday: date >= latestDate });
    } catch (_) {}
  },

  async loadData() {
    this.setData({ loading: true, error: '' });
    try {
      await api.me();
      const data = await api.articles(this.data.date);
      const storedIds = wx.getStorageSync(`ign_selected_${this.data.date}`) || [];
      const selected = new Set(storedIds.map(Number));
      const articles = (data.articles || []).map((item) => {
        const status = item.translation_status || 'none';
        const isDone = status === 'done';
        const selectDisabled = ['done', 'requested', 'needs_review'].includes(status);
        const isSelected = selected.has(Number(item.id));
        return Object.assign({}, item, {
          selected: isSelected,
          cover_image: item.cover_image || (item.images && item.images[0]) || '',
          status_label: statusLabel(status),
          status_class: statusClass(status),
          select_disabled: selectDisabled,
          select_label: isDone ? '完成' : (selectDisabled ? statusLabel(status) : (isSelected ? '已选' : '选择'))
        });
      });
      this.setData({
        articles, selectedIds: Array.from(selected),
        submitText: selected.size ? `提交翻译 (${selected.size})` : '提交翻译',
        isToday: this.data.latestDate ? this.data.date >= this.data.latestDate : this.data.date >= todayNewsDate(),
        pendingCount: articles.filter((a) => !['done', 'requested', 'needs_review'].includes(a.translation_status)).length,
        requestedCount: articles.filter((a) => a.translation_status === 'requested').length,
        doneCount: articles.filter((a) => a.translation_status === 'done').length
      });
      this.applyFilter(this.data.filter, articles);
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
    if (!article || article.select_disabled) return;
    const current = new Set(this.data.selectedIds.map(Number));
    if (current.has(id)) current.delete(id);
    else current.add(id);
    const selectedIds = Array.from(current).sort((a, b) => a - b);
    const selected = new Set(selectedIds);
    const articles = this.data.articles.map((item) => {
      const isSelected = selected.has(Number(item.id));
      return Object.assign({}, item, {
        selected: isSelected,
        select_label: item.select_disabled ? '完成' : (isSelected ? '已选' : '选择')
      });
    });
    this.setData({
      selectedIds,
      submitText: selectedIds.length ? `提交翻译 (${selectedIds.length})` : '提交翻译',
      articles
    });
    wx.setStorageSync(`ign_selected_${this.data.date}`, selectedIds);
    this.applyFilter(this.data.filter, articles);
  },

  setFilter(e) { const filter=e.currentTarget.dataset.filter; this.setData({filter}); this.applyFilter(filter); },

  applyFilter(filter, source) {
    const articles=source || this.data.articles;
    let visible=articles;
    if(filter==='pending') visible=articles.filter((a)=>!['done','requested','needs_review'].includes(a.translation_status));
    else if(filter!=='all') visible=articles.filter((a)=>a.translation_status===filter);
    this.setData({visibleArticles:visible});
  },

  selectAllPending() {
    const ids=this.data.visibleArticles.filter((a)=>!a.select_disabled).map((a)=>Number(a.id));
    const selectedIds=ids.length && ids.every((id)=>this.data.selectedIds.includes(id)) ? [] : ids;
    const selected=new Set(selectedIds);
    const articles=this.data.articles.map((item)=>Object.assign({},item,{selected:selected.has(Number(item.id)),select_label:item.select_disabled?'完成':(selected.has(Number(item.id))?'已选':'选择')}));
    this.setData({selectedIds,articles,submitText:selectedIds.length?`提交翻译 (${selectedIds.length})`:'提交翻译'});
    wx.setStorageSync(`ign_selected_${this.data.date}`, selectedIds);
    this.applyFilter(this.data.filter,articles);
  },

  async submitSelected() {
    if (!this.data.selectedIds.length) return;
    const titles = this.data.articles.filter((item) => this.data.selectedIds.includes(Number(item.id))).map((item) => `#${item.id} ${item.cn_title || item.en_title}`).join('\n');
    const confirmed = await new Promise((resolve) => wx.showModal({
      title: `确认翻译 ${this.data.selectedIds.length} 篇？`,
      content: titles.length > 180 ? `${titles.slice(0, 180)}…` : titles,
      confirmText: '确认提交', success: (res) => resolve(res.confirm), fail: () => resolve(false)
    }));
    if (!confirmed) return;
    this.setData({ submitting: true });
    try {
      try {
        const config = await api.wechatConfig();
        if (config.enabled && config.job_template_id) {
          const consent = await new Promise((resolve) => wx.requestSubscribeMessage({
            tmplIds: [config.job_template_id], success: resolve, fail: () => resolve({})
          }));
          if (consent[config.job_template_id] === 'accept') await api.registerSubscription(config.job_template_id);
        }
      } catch (_) {}
      const res = await api.requestTranslation(this.data.date, this.data.selectedIds);
      if (res.job_id) {
        wx.setStorageSync('ign_job_id', res.job_id);
        await this.loadJob(res.job_id, true);
      }
      wx.showToast({ title: '已提交翻译', icon: 'success' });
      this.setData({ selectedIds: [], submitText: '提交翻译' });
      wx.removeStorageSync(`ign_selected_${this.data.date}`);
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
    wx.setStorageSync('ign_article_nav', { date: this.data.date, ids: this.data.visibleArticles.map((item) => Number(item.id)) });
    wx.navigateTo({ url: `/pages/article/article?date=${this.data.date}&id=${id}` });
  },

  prevDate() {
    const dates = this.data.availableDates || [];
    const index = dates.indexOf(this.data.date);
    const date = index >= 0 && index < dates.length - 1 ? dates[index + 1] : shiftDate(this.data.date, -1);
    this.setData({ date, selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  nextDate() {
    const dates = this.data.availableDates || [];
    const index = dates.indexOf(this.data.date);
    const next = index > 0 ? dates[index - 1] : shiftDate(this.data.date, 1);
    if (this.data.latestDate && next > this.data.latestDate) return;
    if (!this.data.latestDate && this.data.date >= todayNewsDate()) return;
    this.setData({ date: next, selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  today() {
    this.setData({ date: this.data.latestDate || todayNewsDate(), selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  onDateChange(e) {
    const date = e.detail.value;
    if (!date || (this.data.latestDate && date > this.data.latestDate)) return;
    if (this.data.availableDates.length && !this.data.availableDates.includes(date)) {
      wx.showToast({ title: '该新闻日尚未生成', icon: 'none' });
      return;
    }
    this.setData({ date, selectedIds: [], submitText: '提交翻译' });
    this.loadData();
  },

  openJobs() { wx.switchTab({url:'/pages/jobs/jobs'}); }
});
