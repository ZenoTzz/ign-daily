const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..');
const trans={date:'2026-09-06',id:1,url:'https://example.com/story',cn_title:'测试文章：逐段对照与安全保存',en_title:'An article for isolated browser verification',paragraphs:[{cn:'这是第一个中文段落。'.repeat(12),en:'First English paragraph. '.repeat(4)},{cn:'第二段译文。',en:'Second English paragraph. '.repeat(12)}],images:[],pending_dict:[]};
const source=JSON.stringify(trans),sha=crypto.createHash('sha1').update(source).digest('hex');
const server=http.createServer((req,res)=>{
 const file=path.join(root,decodeURIComponent(req.url.split('?')[0]));
 if(!file.startsWith(root)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){res.writeHead(404);res.end();return}
 const ext=path.extname(file);res.setHeader('Content-Type',({'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json'})[ext]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {})});
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let draft={title:'稿件',subtitle:'',summary:'',body:'初稿',updated_at:'2026-09-06T08:00:00Z'},revision='r0',writes=[],conflict=false,deleteFail=false,slow=false,release;
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.origin!==base){await route.fulfill({contentType:'application/javascript',body:'window.tailwind=window.tailwind||{};'});return}
  const p=u.pathname;
  let body;
  if(p.endsWith('/polish')){
   const method=route.request().method();
   if(method==='PUT'){
    body=route.request().postDataJSON();writes.push(body);
    if(slow){slow=false;await new Promise(r=>release=r)}
    if(conflict||body.expected_revision!==revision){await route.fulfill({status:409,json:{detail:'changed'}});return}
    draft={...body,updated_at:'2026-09-06T08:01:00Z'};revision=`r${writes.length}`;
   }
   if(method==='DELETE'){
    if(deleteFail){await route.fulfill({status:503,json:{detail:'unavailable'}});return}
    revision=null;draft={title:trans.cn_title,subtitle:'',summary:'',body:trans.paragraphs.map(p=>p.cn).join('\n')};
   }
   await route.fulfill({json:{ok:true,url:trans.url,exists:revision!==null,revision,draft}});return;
  }
  if(p==='/api/auth/me')body={user:{username:'test'}};
  else if(p.startsWith('/api/files/'))body={content:source,sha};
  else if(p.endsWith('/translations/01.json'))body=trans;
  else if(p.endsWith('/sources/01.json'))body={...trans,paragraphs:trans.paragraphs.map(p=>p.en)};
  else if(p.endsWith('/index.json'))body={date:'2026-09-06',articles:[trans]};
  else if(p==='/data/dict.json')body={};
  else if(p==='/data/2026-09-06/feedback.json')body={};
  if(body!==undefined){await route.fulfill({json:body});return}
  await route.continue();
 });
 await page.goto(base+'/article.html?date=2026-09-06&id=1');
 await page.waitForFunction(()=>window.Alpine && Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishReady);
 await page.waitForTimeout(300);
 await page.screenshot({path:'/private/tmp/article-desktop.png',fullPage:true});
 const desktop=await page.locator('.paired-paragraph').evaluateAll(rows=>rows.map(row=>{
  const cn=row.querySelector('.para-cn-wrap').getBoundingClientRect(),en=row.querySelector('.paired-english').getBoundingClientRect();return {top:Math.abs(cn.top-en.top),cn:cn.width,en:en.width,display:getComputedStyle(row.querySelector('.paired-english')).display};
 }));
 assert.ok(desktop.every(x=>x.top<2&&x.cn>400&&x.en>400&&x.display!=='none'),JSON.stringify(desktop));
 const editToggle=page.getByRole('button',{name:'编辑段落',exact:true});
 assert.equal(await page.locator('.paired-reader .para-edit-btn').first().isVisible(),false);
 await editToggle.focus();await page.keyboard.press('Enter');
 assert.equal(await page.getByRole('button',{name:'完成段落编辑',exact:true}).getAttribute('aria-pressed'),'true');
 await page.locator('.paired-reader .para-edit-btn').first().waitFor({state:'visible'});
 await page.getByRole('button',{name:'译文',exact:true}).click();
 const cnPane=page.locator('.article-reader-layout > .reader-pane.cn');await cnPane.waitFor({state:'visible'});
 assert.equal(await page.locator('.single-source').isVisible(),false);
 const editGap=await cnPane.locator('.para-cn-wrap').first().evaluate(el=>el.querySelector('button').getBoundingClientRect().top-el.querySelector('p').getBoundingClientRect().bottom);
 assert.ok(editGap>=8,`Edit button overlaps paragraph: ${editGap}`);
 await page.screenshot({path:'/private/tmp/article-cn-editing.png',fullPage:true});
 await page.getByRole('button',{name:'完成段落编辑',exact:true}).click();
 await cnPane.locator('.para-edit-btn').first().waitFor({state:'hidden'});
 const more=page.locator('.article-more summary');await more.focus();await page.keyboard.press('Enter');
 assert.equal(await page.getByRole('button',{name:'反馈问题',exact:true}).isVisible(),true);
 await page.keyboard.press('Escape');assert.equal(await page.locator('.article-more').evaluate(el=>el.open),false);
 assert.equal(await more.evaluate(el=>el===document.activeElement),true);
 await page.getByRole('button',{name:'已润色',exact:true}).click();
 const text=page.locator('textarea[x-model="polishData.body"]');
 await text.fill('第一次输入');slow=true;
 await page.waitForFunction(()=>Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishSaving);
 await text.fill('保存期间继续输入');release();
 await page.waitForFunction(()=>!Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishSaving);
 assert.equal(writes.at(-1).body,'保存期间继续输入');assert.equal(writes.length,2);
 conflict=true;await text.fill('本地冲突草稿');await page.getByRole('button',{name:'💾 保存',exact:true}).click();
 await page.waitForFunction(()=>Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishConflict);
 assert.equal(await text.inputValue(),'本地冲突草稿');assert.ok(await page.evaluate(()=>Object.keys(localStorage).some(k=>k.startsWith('ign_polish_draft:'))));
 page.on('dialog',d=>d.accept());conflict=false;
 await page.getByRole('button',{name:'载入服务器版本',exact:true}).click();await page.waitForFunction(()=>!Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishConflict);
 deleteFail=true;await page.getByRole('button',{name:'↻ 重置',exact:true}).click();await page.waitForFunction(()=>Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishError.includes('重置失败'));
 assert.equal(await text.inputValue(),'保存期间继续输入');
 deleteFail=false;await page.getByRole('button',{name:'↻ 重置',exact:true}).click();await page.waitForFunction(()=>Alpine.$data(document.querySelector('[x-data="articleData()"]')).polishRevision===null);
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'对照',exact:true}).first().click();
 await page.locator('.paired-mobile-english summary').first().click();
 await page.waitForTimeout(300);
 await page.screenshot({path:'/private/tmp/article-mobile.png',fullPage:true});
 const mobile=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,english:getComputedStyle(document.querySelector('.paired-english')).display,details:document.querySelector('.paired-mobile-english').open}));
 assert.equal(await page.locator('.polish-grid').isVisible(),false);
 const paneWidth=await page.locator('.paired-reader').evaluate(e=>e.getBoundingClientRect().width);assert.ok(paneWidth>=388);
 assert.equal(mobile.overflow,false);assert.equal(mobile.english,'none');assert.equal(mobile.details,true);
 await page.getByRole('button',{name:'原文',exact:true}).click();
 await page.locator('.single-source').waitFor({state:'visible'});
 const headerHeight=await page.locator('.article-topbar').evaluate(el=>el.getBoundingClientRect().height);
 assert.ok(headerHeight<=76,`Mobile header wraps: ${headerHeight}`);
 await page.getByRole('button',{name:'润色',exact:true}).click();
 await page.locator('.polish-grid').waitFor({state:'visible'});
 assert.equal(await page.locator('.polish-grid').isVisible(),true);
 assert.equal(await page.locator('.paired-reader').isVisible(),false);
 await page.screenshot({path:'/private/tmp/article-mobile-polish.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({desktop,mobile,writes:writes.length,errors}));
 await context.close();
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
