const DICT_CATEGORY_LABELS = { games:'游戏', movies_tv:'影视', companies:'公司', people:'人物', media:'媒体', terms:'术语' };
const DICT_SOURCE_LABELS = { user:'人工确认', ign_cn:'IGN 中国', bilibili:'IGN B站', consensus:'通行译名', ai_guess:'AI 待核实' };

function dictWorkbench() {
  return {
    dictionary:null, entries:[], pending:[], query:'', category:'all', view:'official', page:0, pageSize:40,
    drawer:'', form:{}, duplicate:null, selectedCandidate:null, loading:true, saving:false, toast:'', saveState:'',
    categoryKeys:Object.keys(DICT_CATEGORY_LABELS),
    async init() {
      document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase()==='k') { e.preventDefault(); this.$refs.search.focus(); } });
      await this.reload();
    },
    async reload() {
      this.loading=true;
      try {
        const [dictionary, candidates] = await Promise.all([
          ServerAPI.request('/dict'), ServerAPI.request('/dict/candidates?status=pending').catch(() => ({candidates:[]}))
        ]);
        this.dictionary=dictionary; this.entries=this.flatten(dictionary); this.pending=candidates.candidates||[];
      } catch (error) { this.notify(error.message || '词库加载失败'); }
      finally { this.loading=false; }
    },
    flatten(dictionary) {
      const rows=[];
      this.categoryKeys.forEach(category => Object.entries(dictionary?.[category]||{}).forEach(([en, raw]) => {
        const value=typeof raw==='string'?{cn:raw}:raw||{};
        rows.push({key:`${category}::${en}`,en,cn:value.cn||'',category,source:value.source||'',note:value.note||''});
      }));
      return rows.sort((a,b)=>a.en.localeCompare(b.en));
    },
    get categories() {
      const counts={all:this.entries.length}; this.categoryKeys.forEach(key=>counts[key]=this.entries.filter(x=>x.category===key).length);
      return [{key:'all',label:'全部',count:counts.all},...this.categoryKeys.map(key=>({key,label:this.categoryLabel(key),count:counts[key]}))];
    },
    get filteredEntries() {
      const q=this.query.trim().toLocaleLowerCase();
      return this.entries.filter(item => (this.category==='all'||item.category===this.category) && (!q||`${item.en} ${item.cn} ${item.note}`.toLocaleLowerCase().includes(q)));
    },
    get pagedEntries(){ return this.filteredEntries.slice(this.page*this.pageSize,(this.page+1)*this.pageSize); },
    get pageCount(){ return Math.max(1,Math.ceil(this.filteredEntries.length/this.pageSize)); },
    get pageStart(){ return this.filteredEntries.length?this.page*this.pageSize+1:0; },
    get pageEnd(){ return Math.min((this.page+1)*this.pageSize,this.filteredEntries.length); },
    get filteredCandidates(){ const q=this.query.trim().toLocaleLowerCase(); return this.pending.filter(x=>!q||`${x.en} ${x.cn} ${x.note||''}`.toLocaleLowerCase().includes(q)); },
    get conflicts(){ return this.filteredCandidates.filter(x=>x.has_conflict); },
    get sourceCounts(){ return this.entries.reduce((acc,x)=>(acc[x.source]=(acc[x.source]||0)+1,acc),{}); },
    categoryLabel(key){ return DICT_CATEGORY_LABELS[key]||key; }, sourceLabel(key){ return DICT_SOURCE_LABELS[key]||key||'未标注'; },
    cloudSize(count){ const max=Math.max(...this.categories.map(x=>x.count),1); return Math.round(18+24*Math.sqrt(count/max)); },
    selectEntry(entry){ this.form={...entry,originalCategory:entry.category,originalEn:entry.en}; this.drawer='entry'; },
    openCandidate(){ this.form={en:this.query.trim(),cn:'',category:'games',note:''}; this.duplicate=null; this.checkDuplicate(); this.drawer='candidate'; },
    reviewCandidate(item){ this.selectedCandidate=item; this.form={en:item.en,cn:item.cn,category:item.category||'terms',note:item.note||''}; this.drawer='review'; },
    closeDrawer(){ this.drawer=''; this.selectedCandidate=null; },
    checkDuplicate(){ const q=(this.form.en||'').trim().toLocaleLowerCase(); this.duplicate=q?this.entries.find(x=>x.en.toLocaleLowerCase()===q)||null:null; },
    async saveEntry(){
      this.saving=true; this.saveState='保存中…';
      try {
        if(this.form.originalCategory!==this.form.category) delete this.dictionary[this.form.originalCategory][this.form.originalEn];
        this.dictionary[this.form.category] ||= {};
        const entry={cn:this.form.cn.trim(),source:this.form.source||'user'}; if(this.form.note?.trim())entry.note=this.form.note.trim();
        this.dictionary[this.form.category][this.form.en]=entry;
        this.dictionary._meta ||= {}; this.dictionary._meta.last_updated=new Date().toISOString().slice(0,10);
        await ServerAPI.request('/dict',{method:'PUT',body:JSON.stringify({dictionary:this.dictionary,message:`dict: update ${this.form.en}`})});
        this.entries=this.flatten(this.dictionary); this.closeDrawer(); this.saveState='已保存'; this.notify('词条已保存');
      } catch(error){ this.saveState='保存失败'; this.notify(error.message||'保存失败'); }
      finally{ this.saving=false; setTimeout(()=>this.saveState='',1800); }
    },
    async submitCandidate(){
      this.saving=true;
      try { const result=await ServerAPI.request('/dict/candidates',{method:'POST',body:JSON.stringify({en:this.form.en.trim(),cn:this.form.cn.trim(),category:this.form.category,note:this.form.note.trim()})}); this.closeDrawer(); await this.reload(); this.view='pending'; this.notify(result.duplicate?'该候选已存在':'候选已提交'); }
      catch(error){ this.notify(error.message||'提交失败'); } finally{ this.saving=false; }
    },
    async approveCandidate(){
      this.saving=true;
      try { await ServerAPI.request(`/dict/candidates/${encodeURIComponent(this.selectedCandidate.id)}/approve`,{method:'POST',body:JSON.stringify({cn:this.form.cn.trim(),category:this.form.category,note:this.form.note.trim()})}); this.closeDrawer(); await this.reload(); this.notify('已采纳并写入正式词库'); }
      catch(error){ this.notify(error.message||'采纳失败'); } finally{ this.saving=false; }
    },
    async rejectCandidate(item){
      if(!confirm(`驳回候选“${item.en} → ${item.cn}”？`))return;
      try { await ServerAPI.request(`/dict/candidates/${encodeURIComponent(item.id)}/reject`,{method:'POST'}); await this.reload(); this.notify('候选已驳回'); }
      catch(error){ this.notify(error.message||'驳回失败'); }
    },
    notify(message){ this.toast=message; clearTimeout(this._toastTimer); this._toastTimer=setTimeout(()=>this.toast='',2600); }
  };
}
