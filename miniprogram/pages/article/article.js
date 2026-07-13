const api = require('../../utils/api');

function bodyFromArticle(article) {
  if (!article) return '';
  if (article.body_cn) return article.body_cn;
  if (article.cn_body) return article.cn_body;
  if (Array.isArray(article.paragraphs_cn)) return article.paragraphs_cn.join('\n\n');
  if (Array.isArray(article.paragraphs)) {
    return article.paragraphs.map((item) => item.cn || item.text || '').filter(Boolean).join('\n\n');
  }
  if (article.body) return article.body;
  return '';
}

Page({
  data: {
    date: '',
    id: '',
    article: {},
    images: [],
    bodyText: '',
    showImages: false,
    prevId: null,
    nextId: null,
    reviewLabel: '',
    reviewReason: '',
    summaryLabel: '新闻摘要',
    summaryHint: '',
    waitingText: '',
    canCopyTranslation: false,
    loading: true,
    error: '',
    refreshTimer: null
  },

  async onLoad(query) {
    this.setData({ date: query.date, id: query.id });
    this.updateNavigation(query.date, query.id);
    await this.loadArticle();
    this._hasLoaded = true;
  },

  onShow() {
    if (this._hasLoaded && this.data.date) this.loadArticle(false);
  },

  onHide() {
    this.clearRefreshTimer();
  },

  onUnload() {
    this.clearRefreshTimer();
  },

  async loadArticle(showLoading = true) {
    if (showLoading) this.setData({ loading: true, error: '' });
    try {
      const article = await api.article(this.data.date, this.data.id);
      const status = article.translation_status || 'none';
      const bodyText = bodyFromArticle(article);
      const needsReview = article.manual_release_required || status === 'needs_review';
      const isDone = status === 'done';
      const isRequested = status === 'requested';
      this.setData({
        article,
        error: '',
        bodyText,
        images: Array.isArray(article.images) ? article.images : (article.cover_image ? [article.cover_image] : []),
        reviewLabel: needsReview ? '需要复核' : (isDone ? '已完成' : (isRequested ? '翻译中' : '待选择')),
        reviewReason: article.translation_error || (Array.isArray(article.audit_issues) ? article.audit_issues.join('；') : '') || article.quality_status || '',
        summaryLabel: isDone ? '译文摘要' : '新闻摘要',
        summaryHint: isDone ? '' : '采集阶段摘要 · 非全文译文',
        waitingText: needsReview ? '译文需要复核，暂不提供完整复制。' : (isRequested ? '全文正在翻译，完成后将在这里显示。' : '尚未提交全文翻译。'),
        canCopyTranslation: isDone && Boolean(bodyText)
      });
      if (isRequested) this.startRefreshTimer();
      else this.clearRefreshTimer();
    } catch (err) {
      if (err.statusCode === 401) {
        wx.removeStorageSync('ign_token');
        wx.redirectTo({ url: '/pages/login/login' });
        return;
      }
      if (showLoading) this.setData({ error: err.message || '加载失败' });
    } finally {
      if (showLoading) this.setData({ loading: false });
    }
  },

  copyUrl() {
    const url = this.data.article.url;
    if (!url) {
      wx.showToast({ title: '没有链接', icon: 'none' });
      return;
    }
    wx.setClipboardData({ data: url });
  },

  copyArticle() {
    if (!this.data.canCopyTranslation) {
      wx.showToast({title:'全文完成后才可复制',icon:'none'});
      return;
    }
    const article=this.data.article;
    const text=[article.cn_title || article.title_cn || '', article.subtitle || article.cn_subtitle || '', article.opus_summary || article.summary || '', this.data.bodyText].filter(Boolean).join('\n\n');
    if(!text){wx.showToast({title:'暂无可复制内容',icon:'none'});return;}
    wx.setClipboardData({data:text});
  },

  previewImage(e) {
    const current=e.currentTarget.dataset.src;
    if(current) wx.previewImage({current,urls:this.data.images});
  },

  toggleImages() { this.setData({ showImages: !this.data.showImages }); },

  startRefreshTimer() {
    if (this.data.refreshTimer) return;
    const refreshTimer = setInterval(() => this.loadArticle(false), 5000);
    this.setData({ refreshTimer });
  },

  clearRefreshTimer() {
    if (!this.data.refreshTimer) return;
    clearInterval(this.data.refreshTimer);
    this.setData({ refreshTimer: null });
  },

  updateNavigation(date, id) {
    const nav = wx.getStorageSync('ign_article_nav') || {};
    const ids = nav.date === date && Array.isArray(nav.ids) ? nav.ids.map(Number) : [];
    const index = ids.indexOf(Number(id));
    this.setData({ prevId: index > 0 ? ids[index - 1] : null, nextId: index >= 0 && index < ids.length - 1 ? ids[index + 1] : null });
  },

  goSibling(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    this.clearRefreshTimer();
    this.setData({ id: String(id), article: {}, bodyText: '', images: [], showImages: false, canCopyTranslation: false });
    this.updateNavigation(this.data.date, id);
    this.loadArticle();
  }
});
