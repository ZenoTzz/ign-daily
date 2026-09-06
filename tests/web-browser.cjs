// Isolated browser checks: every site request is served from this checkout or a fixture.
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
const ctx=await browser.newContext({serviceWorkers:'block',viewport:{width:1440,height:1000}});let authenticated=true,usageFail=false,mutations=[];
const root=path.resolve('.'),date='2026-09-06';const article={id:1,url:'https://www.ign.com/articles/test-a',cn_title:'测试文章标题',en_title:'Test article',summary:'已翻译的摘要',category:'游戏新闻',translation_status:'pending'};
const dictionary={games:{Game:{cn:'游戏',source:'user'}}};
await ctx.route('**/*',async route=>{const request=route.request();const url=new URL(request.url());if(url.hostname!=='ign-daily.test')return route.abort();const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 if(url.pathname.startsWith('/api/')){
  const key=url.pathname.slice(4);if(request.method()!=='GET')mutations.push({key,body:request.postDataJSON()});
  if(key==='/auth/browser/login'){authenticated=true;return json({user:{username:'test'}})}
  if(!authenticated)return json({detail:'Not authenticated'},401);
  if(key==='/auth/me')return json({user:{username:'test'}});
  if(key==='/articles')return json({date,total:1,articles:[article]});
  if(key==='/jobs')return json({jobs:[]});
  if(key==='/translations/request')return json({ok:true,triggered:true});
  if(key==='/dict')return json(dictionary);
  if(key==='/dict/candidates')return json({candidates:[]});
  if(key==='/dict/terms' && request.method()==='PUT'){dictionary.games.Game.cn=request.postDataJSON().cn;return json({ok:true})}
  if(key.startsWith('/files/')){
   const filename=decodeURIComponent(key.slice(7));if(usageFail&&filename.startsWith('data/usage/'))return json({detail:'unavailable'},503);
   let data;
   if(filename==='data/usage/deepseek/index.json') data=[date];
   else if(filename===`data/usage/deepseek/${date}.json`)data={records:[{date,model:'deepseek-v4-flash',estimated_cost_usd:1.25,total_tokens:5000,prompt_cache_hit_tokens:1000,prompt_cache_miss_tokens:2000,completion_tokens:2000}]};
   else if(filename==='data/usage/deepseek-runs.json')data=[];
   else if(filename==='data/automation-config.json')data={fulltext_translator:'api',title_translator:'api'};
   else return json({detail:'missing'},404);
   return json({content:JSON.stringify(data),sha:'fixture-sha'});
  }
  return json({detail:'missing'},404);
 }
 if(url.pathname===`/data/${date}/index.json`)return json({date,total:1,articles:[article]});
 let filename=path.join(root,url.pathname==='/'?'index.html':decodeURIComponent(url.pathname));
 if(!filename.startsWith(root+path.sep)||!fs.existsSync(filename)||!fs.statSync(filename).isFile())return route.fulfill({status:404,body:'missing'});
 return route.fulfill({path:filename});
});
const p=await ctx.newPage();let errors=[];p.on('pageerror',e=>errors.push(e.message));
await p.goto(`http://ign-daily.test/index.html?date=${date}`);await p.waitForSelector('.queue-row');
await p.locator('.queue-check input').check();
await p.waitForSelector('.selection-bar:visible');
for (const width of [320,390,768,1024,1440]) {
 await p.setViewportSize({width,height:900});
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);
 const bar=p.locator('.selection-bar');assert.ok(await bar.isVisible());
 const box=await bar.boundingBox();assert.ok(box.x>=0 && box.x+box.width<=width && box.y+box.height<=900);
 assert.ok(await p.getByRole('searchbox',{name:'搜索当前新闻日'}).isVisible());
 assert.ok((await p.locator('.queue-search').boundingBox()).width>=160);
 if(width===390)await p.screenshot({path:'/private/tmp/ign-ui-selection-mobile.png'});
}
await p.getByRole('button',{name:'取消选择',exact:true}).click();await p.locator('.selection-bar').waitFor({state:'hidden'});assert.equal(await p.locator('.selection-bar').isVisible(),false);
assert.equal(await p.locator('.queue-check input').isChecked(),false);
await p.locator('.queue-more summary').click();assert.equal(await p.locator('.queue-check input').isChecked(),false);
await p.locator('.queue-more summary').press('Escape');assert.equal(await p.locator('.queue-more').getAttribute('open'),null);
await p.getByRole('searchbox',{name:'搜索当前新闻日'}).fill('no matching headline');await p.getByRole('button',{name:'查看全部新闻'}).click();await p.waitForSelector('.queue-row');
await p.locator('.queue-check input').check();await p.getByRole('button',{name:'提交翻译',exact:true}).first().click();await p.waitForTimeout(100);
const submitted=mutations.find(x=>x.key==='/translations/request');assert.equal(submitted.body.expected_urls['1'],article.url);assert.equal('trigger_workflow' in submitted.body,false);
assert.equal(mutations.some(x=>x.key==='/workflows/dispatch'),false);
await p.setViewportSize({width:390,height:844});await p.screenshot({path:'/private/tmp/ign-fixed-home-mobile.png',fullPage:true});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),390);
await p.goto('http://ign-daily.test/history.html');await p.waitForFunction(()=>document.querySelectorAll('a[href*="index.html?date="]').length>10);assert.equal(await p.locator('a[href*="undefined"]').count(),0);
await p.goto('http://ign-daily.test/dict.html');await p.getByRole('button',{name:/Game/}).click();await p.locator('input[x-model="form.cn"]').fill('新版游戏');await p.getByRole('button',{name:'保存修改',exact:true}).click();await p.waitForTimeout(150);assert.equal(dictionary.games.Game.cn,'新版游戏');assert.ok(mutations.find(x=>x.key==='/dict/terms').body.expected_entry);
await p.goto('http://ign-daily.test/usage.html');await p.waitForFunction(()=>!document.querySelector('#usageData').hidden);await p.getByRole('button',{name:'总量',exact:true}).click();assert.match(await p.locator('#totalCost').textContent(),/1.25/);
usageFail=true;await p.getByRole('button',{name:'刷新看板'}).click();await p.waitForSelector('#usageError:not([hidden])');assert.match(await p.locator('#usageError').textContent(),/保留/);assert.match(await p.locator('#totalCost').textContent(),/1.25/);
authenticated=false;usageFail=false;await p.reload();await p.waitForSelector('#usageError:not([hidden])');assert.equal(await p.locator('#usageData').isVisible(),false);assert.match(await p.locator('#usageError').textContent(),/登录/);
await p.goto('http://ign-daily.test/dict.html');await p.waitForSelector('.session-notice:visible');assert.equal(await p.locator('.empty-panel:visible').count(),0);
await p.locator('.session-notice button').first().click();await p.waitForSelector('#ign-session-dialog[open]');await p.getByLabel('账号',{exact:true}).fill('test');await p.getByLabel('密码',{exact:true}).fill('fixture-password');await p.getByRole('button',{name:'登录并继续'}).click();await p.waitForSelector('.term-row');assert.equal(new URL(p.url()).pathname,'/dict.html');
assert.deepEqual(errors,[]);console.log('WEB_BROWSER_OK selection identity, read-only refresh, mobile layout, legacy history, dictionary patch, usage/error/login states');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
