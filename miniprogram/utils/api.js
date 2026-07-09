const app = getApp();

function token() {
  return wx.getStorageSync('ign_token') || '';
}

function request(path, options = {}) {
  const headers = Object.assign({}, options.header || {});
  const savedToken = token();
  if (savedToken) headers.Authorization = `Bearer ${savedToken}`;
  if (options.data && !headers['content-type']) headers['content-type'] = 'application/json';

  const url = `${app.globalData.apiBase}${path}`;
  const attempts = options.retryAttempts || 3;

  function once() {
    return new Promise((resolve, reject) => {
      wx.request({
        url,
        method: options.method || 'GET',
        data: options.data,
        header: headers,
        timeout: options.timeout || 20000,
        enableHttp2: false,
        enableQuic: false,
        success(res) {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data);
            return;
          }
          const detail = res.data && (res.data.detail || res.data.message);
          const err = new Error(detail || `请求失败 ${res.statusCode}`);
          err.statusCode = res.statusCode;
          err.data = res.data;
          reject(err);
        },
        fail(err) {
          const raw = err && err.errMsg ? err.errMsg : '网络请求失败';
          const friendly = raw.includes('-101') || raw.includes('timeout') || raw.includes('fail')
            ? '服务器连接失败，请稍后重试；如果开着代理/VPN，请先关闭。'
            : raw;
          const wrapped = new Error(friendly);
          wrapped.raw = raw;
          reject(wrapped);
        }
      });
    });
  }

  return new Promise(async (resolve, reject) => {
    let lastErr = null;
    for (let i = 0; i < attempts; i += 1) {
      try {
        const data = await once();
        resolve(data);
        return;
      } catch (err) {
        lastErr = err;
        if (err.statusCode || i === attempts - 1) break;
        await new Promise(r => setTimeout(r, 500 + i * 700));
      }
    }
    reject(lastErr || new Error('网络请求失败'));
  });
}

function login(username, password) {
  return request('/auth/login', {
    method: 'POST',
    data: { username, password }
  });
}

function me() {
  return request('/auth/me');
}

function articles(date) {
  return request(`/articles?date=${encodeURIComponent(date)}`);
}

function article(date, id) {
  return request(`/articles/${encodeURIComponent(date)}/${encodeURIComponent(id)}`);
}

function requestTranslation(date, ids) {
  return request('/translations/request', {
    method: 'POST',
    data: {
      date,
      ids,
      trigger_workflow: false
    }
  });
}

function job(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}`);
}

function jobs() {
  return request('/jobs?kind=translation&limit=5');
}

module.exports = {
  token,
  request,
  login,
  me,
  articles,
  article,
  requestTranslation,
  job,
  jobs
};
