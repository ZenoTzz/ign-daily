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
    loading: true,
    error: ''
  },

  async onLoad(query) {
    this.setData({ date: query.date, id: query.id });
    await this.loadArticle();
  },

  async loadArticle() {
    this.setData({ loading: true, error: '' });
    try {
      const article = await api.article(this.data.date, this.data.id);
      this.setData({
        article,
        bodyText: bodyFromArticle(article),
        images: Array.isArray(article.images) ? article.images : (article.cover_image ? [article.cover_image] : [])
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
  }
});
