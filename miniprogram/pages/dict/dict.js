const api = require('../../utils/api');
const CATEGORY_LABELS = { games:'游戏', movies_tv:'影视', companies:'公司', people:'人物', media:'媒体', terms:'术语' };

function flatten(dictionary) {
  const rows = [];
  Object.keys(CATEGORY_LABELS).forEach((category) => {
    const group = dictionary[category] || {};
    Object.keys(group).forEach((en) => {
      const raw = group[en];
      const value = typeof raw === 'string' ? { cn: raw } : (raw || {});
      rows.push({ en, cn: value.cn || '', note: value.note || '', category, category_label: CATEGORY_LABELS[category] });
    });
  });
  return rows.sort((a, b) => a.en.localeCompare(b.en));
}

Page({
  data: {
    rows: [], visibleRows: [], query: '', loading: false, error: '', showForm: false, saving: false,
    en: '', cn: '', note: '', category: 'games', categories: Object.keys(CATEGORY_LABELS), categoryLabels: CATEGORY_LABELS
  },
  onShow() {
    if (!api.token()) { wx.redirectTo({ url: '/pages/login/login' }); return; }
    if (!this.data.rows.length) this.loadDictionary();
  },
  onPullDownRefresh() { this.loadDictionary().finally(() => wx.stopPullDownRefresh()); },
  async loadDictionary() {
    this.setData({ loading: true, error: '' });
    try { const rows = flatten(await api.dictionary()); this.setData({ rows }); this.applyFilter(this.data.query, rows); }
    catch (err) { this.setData({ error: err.message || '词库加载失败' }); }
    finally { this.setData({ loading: false }); }
  },
  onSearch(e) { const query = e.detail.value; this.setData({ query }); this.applyFilter(query); },
  applyFilter(query, source) {
    const q = String(query || '').trim().toLowerCase();
    const rows = source || this.data.rows;
    this.setData({ visibleRows: q ? rows.filter((r) => `${r.en} ${r.cn} ${r.note}`.toLowerCase().includes(q)).slice(0, 100) : rows.slice(0, 100) });
  },
  toggleForm() { this.setData({ showForm: !this.data.showForm }); },
  onField(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }); },
  onCategory(e) { this.setData({ category: this.data.categories[Number(e.detail.value)] || 'terms' }); },
  async saveTerm() {
    const en = this.data.en.trim(); const cn = this.data.cn.trim();
    if (!en || !cn) { wx.showToast({ title:'请填写英文和中文', icon:'none' }); return; }
    this.setData({ saving: true });
    try {
      const result = await api.submitDictCandidate(en, cn, this.data.category, this.data.note.trim());
      wx.showToast({ title:result.duplicate ? '候选已存在' : '候选已提交', icon:'success' });
      this.setData({ en:'', cn:'', note:'', showForm:false });
    } catch (err) { wx.showToast({ title:err.message || '保存失败', icon:'none' }); }
    finally { this.setData({ saving:false }); }
  }
});
