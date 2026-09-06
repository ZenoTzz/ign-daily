const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function editor(request) {
  const memory = new Map();
  const context = {URLSearchParams, location:{search:'?date=2026-09-06&id=1'},
    localStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},
    ServerAPI:{request}, setTimeout, clearTimeout, confirm:()=>true,
    window:{addEventListener(){},removeEventListener(){}}, console,
    crypto:require("node:crypto").webcrypto,TextEncoder, GH:{putFile:request}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('assets/article-editor.js','utf8'), context);
  const result = vm.runInContext('articlePolishEditor()',context);
  Object.assign(result,{article:{url:'https://example.com/1'},polishReady:true,polishDirty:true,
    polishData:{title:'title',body:'first'},polishSaving:false,polishSaveTimer:null,
    fmtTime:x=>x,flash(){},buildPolishDraftFromTranslation:()=>({body:'original'})});
  return {result,memory};
}
test('edits during a slow save are submitted with the new revision', async()=>{
  let release;const writes=[];
  const {result}=editor(async(path,options)=>{
    writes.push(JSON.parse(options.body));
    if(writes.length===1) await new Promise(r=>release=r);
    return {revision:`rev-${writes.length}`,draft:{updated_at:'now'}};
  });
  const saving=result.savePolish(false);
  result.polishData.body='second';result.polishEditVersion++;
  result.savePolish(false);
  release();await saving;
  assert.equal(writes.length,2);assert.equal(writes[1].body,'second');
  assert.equal(writes[1].expected_revision,'rev-1');assert.equal(result.polishDirty,false);
});
test('a conflict preserves the local draft and blocks automatic retries',async()=>{
  let calls=0;const {result,memory}=editor(async()=>{calls++;throw Object.assign(new Error('conflict'),{status:409})});
  await result.savePolish(false);await result.savePolish(false);
  assert.equal(calls,1);assert.equal(result.polishDirty,true);assert.equal(result.polishConflict,true);
  assert.equal(JSON.parse([...memory.values()][0]).draft.body,'first');
});
test('failed reset retains local content and the saved version',async()=>{
  const {result}=editor(async()=>{throw new Error('offline')});
  result.polishRevision='rev';await result.resetPolishFromTranslation();
  assert.equal(result.polishData.body,'first');assert.equal(result.polishRevision,'rev');
  assert.match(result.polishError,/重置失败/);
});
test('a successful reset waits for the pending save and uses its revision',async()=>{
  let release;const calls=[];const {result}=editor(async(path,opts)=>{
    calls.push({method:opts.method,payload:JSON.parse(opts.body)});
    if(opts.method==='PUT'){await new Promise(r=>release=r);return {revision:'new',draft:{updated_at:'now'}}}
    return {ok:true};
  });
  const save=result.savePolish(false);const reset=result.resetPolishFromTranslation();
  assert.equal(calls.length,1);release();await Promise.all([save,reset]);
  assert.equal(calls[1].method,'DELETE');assert.equal(calls[1].payload.expected_revision,'new');
  assert.equal(result.polishData.body,'original');assert.equal(result.polishDirty,false);
});
test('restored draft from another revision requires explicit resolution',async()=>{
  const {result,memory}=editor(async()=>({revision:'server',exists:true,draft:{body:'server'}}));
  memory.set(result.polishDraftKey(),JSON.stringify({revision:'old',draft:{body:'local'}}));
  await result.loadPolish();
  assert.equal(result.polishData.body,'local');assert.equal(result.polishConflict,true);
});
test('article inline scripts parse and comparison has a single paired source loop',()=>{
  const html=fs.readFileSync('article.html','utf8');
  for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
  assert.match(html,/paired-paragraph/);assert.match(html,/paired-mobile-english/);
  assert.doesNotMatch(html,/if \(!ServerAPI\.token\(\)\)/);
});

test('translation updates carry the original version even after another read',async()=>{
  let received;const {result}=editor(async(...args)=>{received=args;throw Object.assign(new Error('conflict'),{status:409})});
  result.translationSnapshot={content:'old',sha:'read-version'};
  await assert.rejects(result.writeTranslation('data/date/translations/01.json','changed','edit'));
  assert.equal(received[3].expectedSha,'read-version');
  assert.equal(result.translationSnapshot.sha,'read-version');
  assert.equal(result.translationWriting,false);
});
