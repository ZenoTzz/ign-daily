const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('assets/app.js','utf8');
function setup(fetch=async()=>{throw Error('unexpected fetch')}){
 const memory=new Map();const storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
 const c={navigator:{},console,crypto,TextEncoder,URL,URLSearchParams,Map,Set,structuredClone,location:{hostname:'igndaily.site',search:'',href:'https://igndaily.site/'},localStorage:storage,sessionStorage:storage,document:{documentElement:{classList:{add(){}}}},fetch,setTimeout:fn=>{fn();return 1},clearTimeout(){},setInterval(){},clearInterval(){},window:{addEventListener(){},dispatchEvent(){},scrollY:52,scrollTo(){}},Event:class{}};
 vm.createContext(c);vm.runInContext(source+'\nthis.GH=GH;this.ServerAPI=ServerAPI;this.appData=appData;',c);return c;
}
function response(json,status=200){return {ok:status<400,status,statusText:'',text:async()=>JSON.stringify(json)}}
test('write requests are never blindly retried after ambiguous network failure',async()=>{
 let calls=0;const c=setup(async()=>{calls++;throw Error('lost response')});
 await assert.rejects(c.ServerAPI.request('/translations/request',{method:'POST',body:'{}'}),e=>e.uncertain && e.message.includes('待确认'));assert.equal(calls,1);
});
test('read requests retain bounded network retries',async()=>{let calls=0;const c=setup(async()=>{calls++;throw Error('offline')});await assert.rejects(c.ServerAPI.request('/jobs'));assert.equal(calls,3)});
test('stale file revision is sent unchanged; conflict never fetches a new revision',async()=>{
 const requests=[];const c=setup(async(url,opts)=>{requests.push({url,...opts});return response({detail:'changed'},409)});
 c.GH.revisions.set('data/a.json','opened-revision');await assert.rejects(c.GH.putFile('data/a.json','{"old":1}','save'),e=>e.status===409);
 assert.equal(requests.length,1);assert.equal(JSON.parse(requests[0].body).sha,'opened-revision');
});
test('new file uses explicit absence and successful save keeps submitted revision',async()=>{
 let sent;const c=setup(async(url,o)=>{sent=JSON.parse(o.body);return response({ok:true,sha:'saved-sha'})});
 await assert.rejects(c.GH.putFile('data/new.json','{}','create'),/未读取编辑版本/);
 const result=await c.GH.putFile('data/new.json','{}','create',{expectedSha:null});assert.equal(sent.expected_absent,true);assert.equal(result.sha,'saved-sha');
});
test('selection survives ID reorder by URL and request includes expected identities',async()=>{
 let payload;const c=setup(async(url,o)=>{payload=JSON.parse(o.body);return response({ok:true})});const a=c.appData();a.data={date:'2026-09-06',articles:[{id:1,url:'https://ign.com/a'},{id:2,url:'https://ign.com/b'}]};
 a.toggleArticleSelection(a.data.articles[0]);a.data.articles=[{id:1,url:'https://ign.com/b'},{id:2,url:'https://ign.com/a'}];a.reconcileSelection();assert.deepEqual(Array.from(a.selected),[2]);
 a.flash=()=>{};await a.submitRequestWithServerApi(a.data.date,[2]);assert.equal(payload.expected_urls['2'],'https://ign.com/a');assert.equal('trigger_workflow' in payload,false);
});
test('refresh only reads and title summary readiness is independent of fulltext selection',async()=>{
 const c=setup();const a=c.appData();a.data={date:'2026-09-06',articles:[{id:1,url:'a',cn_title:'标题',summary:'摘要',translation_status:'pending'}]};
 assert.equal(a.titleReadyCount,1);assert.equal(a.pendingSelectionCount,1);a.init=async()=>{};a.flash=()=>{};a.triggerRssOnRefresh=()=>{throw Error('refresh must not start RSS')};await a.refreshData();
});
test('editing a dictionary entry sends one entry plus its original value, never the whole dictionary',async()=>{
 const c=setup();vm.runInContext(fs.readFileSync('assets/dict-workbench.js','utf8'),c);const d=c.dictWorkbench();d.dictionary={games:{Old:{cn:'旧',source:'user'},Another:{cn:'其他',source:'user'}}};d.entries=d.flatten(d.dictionary);d.selectEntry(d.entries.find(x=>x.en==='Old'));d.form.cn='修改';let sent;
 c.ServerAPI.request=async(path,opts)=>{assert.equal(path,'/dict/terms');sent=JSON.parse(opts.body);return {ok:true}};d.reload=async()=>{};d.notify=()=>{};await d.saveEntry();
 assert.equal(sent.cn,'修改');assert.equal(sent.expected_entry.cn,'旧');assert.equal('dictionary' in sent,false);assert.equal(d.dictionary.games.Old.cn,'旧');
});
