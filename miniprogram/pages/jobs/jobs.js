const api = require('../../utils/api');

function decorate(job) {
  const statusMap = { queued: '排队中', running: '翻译中', done: '已完成', failed: '失败' };
  const ids = Array.isArray(job.ids) ? job.ids : [];
  return Object.assign({}, job, {
    status_label: statusMap[job.status] || job.status || '未知',
    ids_text: ids.map((id) => `#${id}`).join('、'),
    progress_value: Number(job.progress || (job.status === 'done' ? 100 : 0)),
    status_class: `status-${job.status || 'queued'}`,
    errors: Array.isArray(job.errors) ? job.errors : []
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
  }
});
