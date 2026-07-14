function learningConsole() {
  return {
    tab: 'week',
    loading: true,
    error: '',
    toast: '',
    query: '',
    weekly: null,
    activeRules: [],
    observations: { active: [], archived: [] },
    history: [],
    feedback: {},
    latestWeekId: '',

    async fetchJson(path, fallback = null) {
      try {
        const file = await GH.getFile(path);
        if (!file?.content) return fallback;
        return JSON.parse(file.content);
      } catch (_) {
        return fallback;
      }
    },

    async init() {
      this.loading = true;
      const [weekly, active, observations, index] = await Promise.all([
        this.fetchJson('data/learning/weekly/latest.json'),
        this.fetchJson('data/learning/active-rules.json', { rules: [] }),
        this.fetchJson('data/learning/observations.json', { active: [], archived: [] }),
        this.fetchJson('data/learning/weekly/_index.json', { weeks: [] }),
      ]);
      this.weekly = weekly;
      this.activeRules = active?.rules || [];
      this.observations = observations || { active: [], archived: [] };
      const summaries = index?.summaries || {};
      this.latestWeekId = index?.latest || weekly?.week_id || '';
      this.history = (index?.weeks || []).slice().reverse().map(weekId => summaries[weekId] || { week_id: weekId, summary: {} });
      if (weekly?.week_id) {
        this.feedback = await this.fetchJson(`data/learning/weekly/${weekly.week_id}_feedback.json`, {}) || {};
      }
      this.loading = false;
      if (!weekly) this.error = '尚未生成新版学习周报。';
    },

    get decisions() { return this.weekly?.decisions || this.weekly?.candidates || []; },
    get conflicts() { return this.weekly?.conflicts || []; },
    get dictionaryCandidates() { return this.weekly?.dictionary_candidates || []; },
    get weekSummary() { return this.weekly?.summary || {}; },
    get readOnlyHistory() { return Boolean(this.weekly?.week_id && this.latestWeekId && this.weekly.week_id !== this.latestWeekId); },
    get weekRange() {
      const range = this.weekly?.range || {};
      return range.start && range.end ? `${range.start.replaceAll('-', '.')} — ${range.end.replaceAll('-', '.')}` : '日期范围待生成';
    },

    filtered(items) {
      const q = this.query.trim().toLowerCase();
      if (!q) return items || [];
      return (items || []).filter(item => [item.title, item.rule, item.scope, item.category].join(' ').toLowerCase().includes(q));
    },

    async selectWeek(weekId) {
      const report = await this.fetchJson(`data/learning/weekly/${weekId}.json`);
      if (!report) return this.flash('无法读取这份历史周报。');
      this.weekly = report;
      this.feedback = await this.fetchJson(`data/learning/weekly/${weekId}_feedback.json`, {}) || {};
      this.tab = 'week';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async saveDecision(rule, decision) {
      if (this.readOnlyHistory) return this.flash('历史周报是只读快照。');
      if (!this.weekly?.week_id || !rule?.id) return;
      const messages = {
        accept: '采纳，进入长期规则。',
        reject: '否定，这不是我的长期偏好。',
        observe: '暂缓，继续观察。',
      };
      let text = messages[decision];
      if (decision === 'limit') {
        text = window.prompt('请写明这条规则适用的文章类型或语境：', this.feedback[rule.id] || '限定：仅适用于');
        if (!text?.trim()) return;
      }
      this.feedback[rule.id] = text;
      try {
        await GH.putFile(
          `data/learning/weekly/${this.weekly.week_id}_feedback.json`,
          JSON.stringify(this.feedback, null, 2),
          `weekly learning feedback ${this.weekly.week_id}: ${rule.id}`,
        );
        this.flash('决定已保存，夜间学习下次会处理。');
      } catch (error) {
        this.flash(`保存失败：${error.message}`);
      }
    },

    flash(message) {
      this.toast = message;
      window.clearTimeout(this._toastTimer);
      this._toastTimer = window.setTimeout(() => { this.toast = ''; }, 2600);
    },
  };
}
