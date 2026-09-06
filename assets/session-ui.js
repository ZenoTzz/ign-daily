// Shared cookie-based login. No credentials are persisted in browser storage.
(() => {
  function setup() {
    if (!window.ServerAPI || document.getElementById('ign-session-dialog')) return;
    const tools = document.createElement('div');
    tools.className = 'ign-session-tools';
    tools.innerHTML = `<details class="ign-page-menu"><summary aria-label="打开工作区导航">导航</summary><nav aria-label="工作区"><a href="index.html">工作台</a><a href="index.html#tasks">任务</a><a href="dict.html">词库</a><a href="learning.html">学习</a><a href="usage.html">用量</a><a href="history.html">新闻归档</a><a href="calendar.html">游戏日历</a><button type="button" class="ign-menu-account">登录账号</button></nav></details><button type="button" class="ign-session-button">登录账号</button>`;
    const mount = document.querySelector('.nav-actions, .article-topbar nav, .dict-top-actions, .topbar .nav, header > div') || document.body;
    mount.append(tools);
    const dialog = document.createElement('dialog');
    dialog.id = 'ign-session-dialog'; dialog.className = 'ign-session-dialog';
    dialog.setAttribute('aria-labelledby', 'ign-session-title');
    dialog.innerHTML = `<form><h2 id="ign-session-title">登录 IGN Daily</h2><p>使用网站账号，在当前页面继续操作。</p><label>账号<input name="username" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><p class="ign-session-error" role="alert"></p><div class="ign-session-actions"><button type="button" data-close>取消</button><button type="submit">登录并继续</button></div></form><section hidden class="ign-account-info"><h2>账号</h2><p data-account></p><button type="button" data-logout>退出登录</button><button type="button" data-close>关闭</button></section>`;
    document.body.append(dialog);
    const button = tools.querySelector('.ign-session-button');
    const form = dialog.querySelector('form');
    const info = dialog.querySelector('.ign-account-info');
    const error = dialog.querySelector('.ign-session-error');
    let user = '', busy = false;
    const open = () => {
      form.hidden = !!user; info.hidden = !user; error.textContent = '';
      info.querySelector('[data-account]').textContent = user ? `已登录：${user}` : '';
      dialog.showModal();
    };
    window.IGNSession = {open};
    button.addEventListener('click', open);
    tools.querySelector('.ign-menu-account').addEventListener('click', () => { tools.querySelector('details').open = false; open(); });
    dialog.querySelectorAll('[data-close]').forEach(e => e.addEventListener('click', () => { if (!busy) dialog.close(); }));
    dialog.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
    form.addEventListener('submit', async e => {
      e.preventDefault(); if (busy) return;
      busy = true; form.querySelector('button[type=submit]').disabled = true;
      try {
        await ServerAPI.login(form.elements.username.value.trim(), form.elements.password.value);
        form.elements.password.value = '';
        location.reload();
      } catch (e) { error.textContent = e.message; }
      finally { busy = false; form.querySelector('button[type=submit]').disabled = false; }
    });
    dialog.querySelector('[data-logout]').addEventListener('click', async () => {
      if (busy) return; busy = true;
      try {
        await ServerAPI.logout();
        GH.revisions.clear();
        location.reload();
      } catch (e) { info.querySelector('[data-account]').textContent = e.message; }
      finally { busy = false; }
    });
    async function refresh() {
      try { const result = await ServerAPI.me(); user = result?.user?.username || ''; }
      catch (_) { user = ''; }
      button.textContent = user ? `账号：${user}` : '登录账号';
      tools.querySelector('.ign-menu-account').textContent = button.textContent;
    }
    window.addEventListener('ign-auth-changed', refresh);
    refresh();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup, {once:true});
  else setup();
})();
