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
    loading: true,
    error: ''
  },

  async onLoad(query) {
    this.setData({ date: query.date, id: query.id });
    this.updateNavigation(query.date, query.id);
    await this.loadArticle();
  },

  async loadArticle() {
    this.setData({ loading: true, error: '' });
    try {
      const article = await api.article(this.data.date, this.data.id);
      this.setData({
        article,
        bodyText: bodyFromArticle(article),
        images: Array.isArray(article.images) ? article.images : (article.cover_image ? [article.cover_image] : []),
        reviewLabel: article.manual_release_required || article.translation_status === 'needs_review' ? '需要复核' : (article.translation_status === 'done' ? '已完成' : '待处理'),
        reviewReason: article.translation_error || (Array.isArray(article.audit_issues) ? article.audit_issues.join('；') : '') || article.quality_status || ''
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

  copyUrl() {
    const url = this.data.article.url;
    if (!url) {
      wx.showToast({ title: '没有链接', icon: 'none' });
      return;
    }
    wx.setClipboardData({ data: url });
  },

  copyArticle() {
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

  updateNavigation(date, id) {
    const nav = wx.getStorageSync('ign_article_nav') || {};
    const ids = nav.date === date && Array.isArray(nav.ids) ? nav.ids.map(Number) : [];
    const index = ids.indexOf(Number(id));
    this.setData({ prevId: index > 0 ? ids[index - 1] : null, nextId: index >= 0 && index < ids.length - 1 ? ids[index + 1] : null });
  },

  goSibling(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    this.setData({ id: String(id), article: {}, bodyText: '', images: [], showImages: false });
    this.updateNavigation(this.data.date, id);
    this.loadArticle();
  }
});
