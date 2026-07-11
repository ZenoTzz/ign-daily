const api = require('../../utils/api');

Page({
  data: { username:'', wechatBound:false, loading:true },
  onShow() {
    if (!api.token()) { wx.redirectTo({ url:'/pages/login/login' }); return; }
    this.loadMe();
  },
  async loadMe() {
    this.setData({ loading:true });
    try { const result=await api.me(); const username=(result.user && result.user.username) || wx.getStorageSync('ign_username') || ''; this.setData({ username, wechatBound:!!(result.user && result.user.wechat_bound) }); }
    catch (err) { if(err.statusCode===401) this.logout(); else wx.showToast({title:err.message||'账号加载失败',icon:'none'}); }
    finally { this.setData({loading:false}); }
  },
  logout(){wx.removeStorageSync('ign_token');wx.removeStorageSync('ign_job_id');wx.reLaunch({url:'/pages/login/login'});}
});
