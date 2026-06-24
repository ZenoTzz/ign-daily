const app = getApp();

function token() {
  return wx.getStorageSync('ign_token') || '';
}

function request(path, options = {}) {
  const headers = Object.assign({}, options.header || {});
  const savedToken = token();
  if (savedToken) headers.Authorization = `Bearer ${savedToken}`;
  if (options.data && !headers['content-type']) headers['content-type'] = 'application/json';

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.apiBase}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: headers,
      timeout: 20000,
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
        reject(new Error(err.errMsg || '网络请求失败'));
      }
    });
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
      trigger_workflow: true
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
