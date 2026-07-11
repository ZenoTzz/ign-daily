const api = require('../../utils/api');

Page({
  data: {
    username: wx.getStorageSync('ign_username') || '',
    password: '',
    loading: false,
    checkingWechat: true,
    bindingRequired: false,
    bindToken: '',
    statusText: '正在确认微信身份…'
  },

  onLoad() {
    if (api.token()) {
      wx.switchTab({ url: '/pages/index/index' });
      return;
    }
    this.tryWechatLogin();
  },

  async tryWechatLogin() {
    this.setData({ checkingWechat: true, statusText: '正在确认微信身份…' });
    try {
      const loginResult = await new Promise((resolve, reject) => wx.login({ success: resolve, fail: reject }));
      if (!loginResult.code) throw new Error('微信登录凭证为空');
      const result = await api.wechatLogin(loginResult.code);
      if (result.bound && result.token) {
        this.finishLogin(result);
        return;
      }
      this.setData({ bindingRequired: true, bindToken: result.bind_token || '', statusText: '首次使用，请绑定管理员账号' });
    } catch (err) {
      this.setData({ bindingRequired: false, bindToken: '', statusText: err.message === 'WeChat login is not configured' ? '微信登录尚未配置，可使用服务器账号登录' : '微信身份确认失败，可使用服务器账号登录' });
    } finally { this.setData({ checkingWechat: false }); }
  },

  finishLogin(result) {
    const username = result.user && result.user.username ? result.user.username : this.data.username;
    wx.setStorageSync('ign_token', result.token);
    wx.setStorageSync('ign_username', username);
    wx.switchTab({ url: '/pages/index/index' });
  },

  onUsernameInput(e) {
    this.setData({ username: e.detail.value });
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value });
  },

  async submit() {
    const username = this.data.username.trim();
    const password = this.data.password;
    if (!username || !password) {
      wx.showToast({ title: '请输入账号密码', icon: 'none' });
      return;
    }
    this.setData({ loading: true });
    try {
      const res = this.data.bindingRequired && this.data.bindToken
        ? await api.bindWechat(this.data.bindToken, username, password)
        : await api.login(username, password);
      this.finishLogin(res);
    } catch (err) {
      wx.showToast({ title: err.message || '登录失败', icon: 'none' });
    } finally {
      this.setData({ loading: false, password: '' });
    }
  }
});
