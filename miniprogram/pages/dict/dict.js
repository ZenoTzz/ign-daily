const api = require('../../utils/api');
const CATEGORY_LABELS = { games:'游戏', movies_tv:'影视', companies:'公司', people:'人物', media:'媒体', terms:'术语' };

function flatten(dictionary) {
  const rows=[];
  Object.keys(CATEGORY_LABELS).forEach(category => Object.keys(dictionary[category]||{}).forEach(en => {
    const raw=dictionary[category][en]; const value=typeof raw==='string'?{cn:raw}:raw||{};
    rows.push({en,cn:value.cn||'',note:value.note||'',category,category_label:CATEGORY_LABELS[category]});
  }));
  return rows.sort((a,b)=>a.en.localeCompare(b.en));
}

Page({
  data:{ rows:[],visibleRows:[],pending:[],visiblePending:[],query:'',tab:'official',loading:false,error:'',showForm:false,saving:false,duplicate:null,en:'',cn:'',note:'',category:'games',categories:Object.keys(CATEGORY_LABELS),categoryLabels:CATEGORY_LABELS },
  onShow(){ if(!api.token()){wx.redirectTo({url:'/pages/login/login'});return;} if(!this.data.rows.length)this.loadDictionary(); },
  onPullDownRefresh(){this.loadDictionary().finally(()=>wx.stopPullDownRefresh());},
  async loadDictionary(){
    this.setData({loading:true,error:''});
    try{const [dictionary,result]=await Promise.all([api.dictionary(),api.dictCandidates().catch(()=>({candidates:[]}))]);const rows=flatten(dictionary);const pending=result.candidates||[];this.setData({rows,pending});this.applyFilter(this.data.query,rows,pending);}
    catch(err){this.setData({error:err.message||'词库加载失败'});}finally{this.setData({loading:false});}
  },
  changeTab(e){this.setData({tab:e.currentTarget.dataset.tab});},
  onSearch(e){const query=e.detail.value;this.setData({query});this.applyFilter(query);},
  applyFilter(query,sourceRows,sourcePending){const q=String(query||'').trim().toLowerCase();const rows=sourceRows||this.data.rows;const pending=sourcePending||this.data.pending;this.setData({visibleRows:(q?rows.filter(r=>`${r.en} ${r.cn} ${r.note}`.toLowerCase().includes(q)):rows).slice(0,100),visiblePending:(q?pending.filter(r=>`${r.en} ${r.cn} ${r.note||''}`.toLowerCase().includes(q)):pending).slice(0,100)});},
  openForm(){this.setData({showForm:true,en:this.data.query.trim(),duplicate:null});this.checkDuplicate(this.data.query);},
  closeForm(){if(!this.data.saving)this.setData({showForm:false});},
  stopBubble(){},
  onField(e){const field=e.currentTarget.dataset.field;const value=e.detail.value;this.setData({[field]:value});if(field==='en')this.checkDuplicate(value);},
  checkDuplicate(value){const q=String(value||'').trim().toLowerCase();this.setData({duplicate:q?this.data.rows.find(r=>r.en.toLowerCase()===q)||null:null});},
  onCategory(e){this.setData({category:this.data.categories[Number(e.detail.value)]||'terms'});},
  async saveTerm(){const en=this.data.en.trim(),cn=this.data.cn.trim();if(!en||!cn){wx.showToast({title:'请填写英文和中文',icon:'none'});return;}this.setData({saving:true});try{const result=await api.submitDictCandidate(en,cn,this.data.category,this.data.note.trim());wx.showToast({title:result.duplicate?'候选已存在':'候选已提交',icon:'success'});this.setData({en:'',cn:'',note:'',showForm:false,tab:'pending'});await this.loadDictionary();}catch(err){wx.showToast({title:err.message||'保存失败',icon:'none'});}finally{this.setData({saving:false});}}
});
