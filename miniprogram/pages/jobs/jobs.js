const api = require('../../utils/api');

function decorate(job) {
  const statusMap = { queued: '排队中', running: '翻译中', done: '已完成', failed: '失败' };
  const ids = Array.isArray(job.ids) ? job.ids : [];
  const results = Array.isArray(job.results) ? job.results : [];
  const errors = Array.isArray(job.errors) ? job.errors : [];
  const progressItems = Array.isArray(job.progress_items) ? job.progress_items : [];
  const itemById = {};
  progressItems.forEach((item) => { itemById[Number(item.article_id || item.id)] = item; });
  const resultItems = ids.map((id) => {
    const progress = itemById[Number(id)] || {};
    const error = errors.find((item) => Number(item.article_id || item.id) === Number(id));
    const done = results.some((item) => Number(item.article_id || item.id) === Number(id)) || progress.status === 'done' || job.status === 'done';
    return { id, label: error ? '失败' : (done ? '完成' : (progress.step_label || '等待')), message: error ? (error.message || error.error) : (progress.message || ''), item_class: error ? 'status-failed' : (done ? 'status-done' : 'status-running') };
  });
  return Object.assign({}, job, {
    status_label: statusMap[job.status] || job.status || '未知',
    ids_text: ids.map((id) => `#${id}`).join('、'),
    progress_value: Number(job.progress || (job.status === 'done' ? 100 : 0)),
    status_class: `status-${job.status || 'queued'}`,
    errors,
    result_items: resultItems,
    done_count: resultItems.filter((item) => item.label === '完成').length,
    eta_text: job.status === 'running' && job.eta_seconds ? `约剩 ${Math.max(1, Math.ceil(Number(job.eta_seconds) / 60))} 分钟` : ''
  });
}

Page({
  data: { jobs: [], loading: false, error: '' },
  onShow() {
    if (!api.token()) { wx.redirectTo({ url: '/pages/login/login' }); return; }
    this.loadJobs();
  },
  onPullDownRefresh() { this.loadJobs().finally(() => wx.stopPullDownRefresh()); },
  async loadJobs() {
    this.setData({ loading: true, error: '' });
    try {
      const result = await api.jobs();
      this.setData({ jobs: (result.jobs || []).map(decorate) });
    } catch (err) {
      if (err.statusCode === 401) { wx.removeStorageSync('ign_token'); wx.redirectTo({ url: '/pages/login/login' }); return; }
      this.setData({ error: err.message || '任务加载失败' });
    } finally { this.setData({ loading: false }); }
  },
  openDate(e) {
    const date = e.currentTarget.dataset.date;
    if (date) { wx.setStorageSync('ign_target_date', date); wx.switchTab({ url: '/pages/index/index' }); }
  },
  openArticle(e) {
    wx.navigateTo({ url: `/pages/article/article?date=${e.currentTarget.dataset.date}&id=${e.currentTarget.dataset.id}` });
  }
});
