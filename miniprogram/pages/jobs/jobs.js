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
  const etaMin = Number(job.eta_min_seconds);
  const etaMax = Number(job.eta_max_seconds);
  let etaText = '';
  if (job.status === 'queued' || job.estimate_kind === 'scheduled') etaText = '等待下一翻译窗口';
  else if (job.status === 'running' && Number.isFinite(etaMin) && Number.isFinite(etaMax) && etaMax > 0) {
    const minMinutes = Math.max(1, Math.floor(etaMin / 60));
    const maxMinutes = Math.max(minMinutes, Math.ceil(etaMax / 60));
    const range = maxMinutes < 60
      ? `${minMinutes}–${maxMinutes} 分钟`
      : `${Math.max(1, Math.floor(minMinutes / 60))}–${Math.max(1, Math.ceil(maxMinutes / 60))} 小时`;
    etaText = job.estimate_kind === 'uncertain'
      ? `修复中，通常还需 ${range}，可能延长`
      : `通常还需 ${range}`;
  }
  return Object.assign({}, job, {
    status_label: statusMap[job.status] || job.status || '未知',
    ids_text: ids.map((id) => `#${id}`).join('、'),
    progress_value: Number(job.progress || (job.status === 'done' ? 100 : 0)),
    status_class: `status-${job.status || 'queued'}`,
    errors,
    result_items: resultItems,
    done_count: resultItems.filter((item) => item.label === '完成').length,
    eta_text: etaText
  });
}

Page({
  data: { jobs: [], loading: false, error: '' },
  onShow() {
    if (!api.token()) { wx.redirectTo({ url: '/pages/login/login' }); return; }
    this.loadJobs(!this.data.jobs.length);
  },
  onPullDownRefresh() { this.loadJobs(false).finally(() => wx.stopPullDownRefresh()); },
  async loadJobs(showLoading = false) {
    if (showLoading) this.setData({ loading: true });
    this.setData({ error: '' });
    try {
      const result = await api.jobs();
      this.setData({ jobs: (result.jobs || []).map(decorate) });
    } catch (err) {
      if (err.statusCode === 401) { wx.removeStorageSync('ign_token'); wx.redirectTo({ url: '/pages/login/login' }); return; }
      this.setData({ error: err.message || '任务加载失败' });
    } finally { if (showLoading) this.setData({ loading: false }); }
  },
  openDate(e) {
    const date = e.currentTarget.dataset.date;
    if (date) { wx.setStorageSync('ign_target_date', date); wx.switchTab({ url: '/pages/index/index' }); }
  },
  openArticle(e) {
    wx.navigateTo({ url: `/pages/article/article?date=${e.currentTarget.dataset.date}&id=${e.currentTarget.dataset.id}` });
  }
});
