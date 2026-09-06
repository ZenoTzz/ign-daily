"""Run the actual FastAPI/Pydantic stack against a temporary runtime only."""
from pathlib import Path
import http.cookiejar, json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, uuid
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ign-http-test-') as temp:
    base=Path(temp);app=base/'app';api=base/'api';(app/'data/2026-09-06').mkdir(parents=True);api.mkdir()
    day=app/'data/2026-09-06';url='https://example.com/fixture'
    (day/'index.json').write_text(json.dumps({'date':'2026-09-06','articles':[{'id':1,'url':url,'cn_title':'标题','summary':'摘要'}]}))
    (app/'data/dict.json').write_text(json.dumps({'games':{'Game':{'cn':'游戏','source':'user'}}}))
    (app/'data/automation-config.json').write_text(json.dumps({'fulltext_translator':'codex'}))
    password=uuid.uuid4().hex
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'IGN_DAILY_REPO_PATH':str(app),'IGN_DAILY_API_DIR':str(api),'IGN_DAILY_API_DB':str(api/'auth.sqlite3'),'IGN_DAILY_WRITE_LOCK':str(base/'write.lock'),'IGN_DAILY_STORAGE_MODE':'local','IGN_DAILY_ADMIN_USER':'fixture','IGN_DAILY_ADMIN_PASSWORD':password,'IGN_DAILY_COOKIE_SECURE':'0','PYTHONPATH':str(root/'server_api')}
    with (base/'server.log').open('w') as log:
      process=subprocess.Popen([sys.executable,'-m','uvicorn','ign_daily_api:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
      try:
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def request(path,body=None,method='GET',status=200):
          req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
          try:r=opener.open(req,timeout=5)
          except urllib.error.HTTPError as e:r=e
          assert r.status==status,(path,r.status,r.read().decode())
          return json.loads(r.read())
        for _ in range(100):
          try:request('/health');break
          except urllib.error.URLError:
            if process.poll() is not None:raise RuntimeError('Isolated API did not start: '+(base/'server.log').read_text()[-2500:])
            time.sleep(.1)
        request('/dict',status=401)
        request('/auth/browser/login',{'username':'fixture','password':password},'POST')
        old=request('/dict')['games']['Game']
        patch={'original_category':'games','original_en':'Game','expected_entry':old,'category':'games','en':'Game','cn':'新游戏','source':'consensus'}
        request('/dict/terms',patch,'PUT');assert request('/dict')['games']['Game']['source']=='consensus'
        request('/dict/terms',patch,'PUT',409)
        request('/files/data/created.json',{'content':'{}','expected_absent':True},'PUT')
        request('/files/data/created.json',{'content':'{}','expected_absent':True},'PUT',409)
        endpoint='/articles/2026-09-06/1/polish';assert request(endpoint)['revision'] is None
        save={'url':url,'expected_revision':None,'title':'润色标题','subtitle':'','summary':'','body':'正文'}
        saved=request(endpoint,save,'PUT');request(endpoint,save,'PUT',409)
        request(endpoint,{'url':url,'expected_revision':saved['revision']},'DELETE')
        assert request(endpoint)['exists'] is False
        request('/translations/request',{'date':'2026-09-06','ids':[1],'expected_urls':{'1':'https://wrong.test'}},'POST',409)
        assert not (day/'requests.json').exists()
        queued=request('/translations/request',{'date':'2026-09-06','ids':[1],'expected_urls':{'1':url}},'POST')
        assert queued.get('job_id')
        request('/codex/jobs/'+queued['job_id']+'/progress',{'status':'done'},'POST',409)
        print('API_HTTP_OK: real cookie auth, dictionary CAS/source, create CAS, polish CAS/delete, identity gate, completion gate')
      finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
