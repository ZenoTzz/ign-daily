const api = require('../../utils/api');

Page({
  data: { username:'', loading:true, showEdit:false, saving:false, currentPassword:'', newUsername:'', newPassword:'', confirmPassword:'' },
  onShow() {
    if (!api.token()) { wx.redirectTo({ url:'/pages/login/login' }); return; }
    this.loadMe();
  },
  async loadMe() {
    this.setData({ loading:true });
    try { const result=await api.me(); const username=(result.user && result.user.username) || wx.getStorageSync('ign_username') || ''; this.setData({ username, newUsername:username }); }
    catch (err) { if(err.statusCode===401) this.logout(); else wx.showToast({title:err.message||'账号加载失败',icon:'none'}); }
    finally { this.setData({loading:false}); }
  },
  toggleEdit() { this.setData({showEdit:!this.data.showEdit,currentPassword:'',newPassword:'',confirmPassword:''}); },
  onField(e) { this.setData({[e.currentTarget.dataset.field]:e.detail.value}); },
  async saveAccount() {
    if(!this.data.currentPassword){wx.showToast({title:'请输入当前密码',icon:'none'});return;}
    if(this.data.newPassword!==this.data.confirmPassword){wx.showToast({title:'两次新密码不一致',icon:'none'});return;}
    this.setData({saving:true});
    try{
      await api.updateAccount(this.data.currentPassword,this.data.newUsername.trim(),this.data.newPassword);
      wx.showModal({title:'账号已更新',content:'为了安全，请使用新账号重新登录。',showCancel:false,success:()=>this.logout()});
    }catch(err){wx.showToast({title:err.message||'保存失败',icon:'none'});}
    finally{this.setData({saving:false});}
  },
  logout(){wx.removeStorageSync('ign_token');wx.removeStorageSync('ign_job_id');wx.reLaunch({url:'/pages/login/login'});}
});
