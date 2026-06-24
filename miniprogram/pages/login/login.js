const api = require('../../utils/api');

Page({
  data: {
    username: wx.getStorageSync('ign_username') || '',
    password: '',
    loading: false
  },

  onLoad() {
    if (api.token()) {
      wx.redirectTo({ url: '/pages/index/index' });
    }
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
      const res = await api.login(username, password);
      wx.setStorageSync('ign_token', res.token);
      wx.setStorageSync('ign_username', res.user && res.user.username ? res.user.username : username);
      wx.redirectTo({ url: '/pages/index/index' });
    } catch (err) {
      wx.showToast({ title: err.message || '登录失败', icon: 'none' });
    } finally {
      this.setData({ loading: false, password: '' });
    }
  }
});
