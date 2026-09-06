// Editing state is tied to the URL and the version originally read.
function articlePolishEditor() {
  return {
    polishRevision: null, polishReady: false, polishError: '', polishConflict: false,
    polishEditVersion: 0, polishResetting: false, polishSavePromise: null,
    translationSnapshot: null, translationWriting: false,
    polishEndpoint() {
      const params = new URLSearchParams(location.search);
      return `/articles/${encodeURIComponent(params.get('date'))}/${encodeURIComponent(params.get('id'))}/polish`;
    },
    polishDraftKey() { return `ign_polish_draft:${new URLSearchParams(location.search).get('date')}:${this.article.url}`; },
    rememberPolishDraft() {
      try { localStorage.setItem(this.polishDraftKey(), JSON.stringify({draft: this.polishData, revision: this.polishRevision})); }
      catch (_) { this.polishError = '浏览器无法保存本地草稿，请保持页面打开并手动保存。'; }
    },
    installDraftGuard() {
      this._draftGuard = e => {
        if (this.polishDirty || this.polishSaving || this.polishResetting) { e.preventDefault(); e.returnValue = ''; }
      };
      window.addEventListener('beforeunload', this._draftGuard);
    },
    destroy() {
      clearTimeout(this.polishSaveTimer);
      if (this.polishDirty) this.rememberPolishDraft();
      window.removeEventListener('beforeunload', this._draftGuard);
    },
    async loadPolish() {
      this.polishReady = false;
      this.polishError = '';
      try {
        const result = await ServerAPI.request(this.polishEndpoint());
        if (result.url && result.url !== this.article.url) throw new Error('文章编号已变化，请返回列表重新打开。');
        this.polishData = {...result.draft};
        this.polishRevision = result.revision;
        this.polishExists = result.exists;
        this.polishStatus = result.exists ? '已润色' : '润色';
        this.polishSavedAt = result.draft.updated_at ? this.fmtTime(result.draft.updated_at) : '';
        this.polishReady = true;
        let local;
        try { local = JSON.parse(localStorage.getItem(this.polishDraftKey()) || 'null'); } catch (_) {}
        if (local?.draft) {
          this.polishData = local.draft;
          this.polishDirty = true;
          this.polishEditVersion++;
          this.polishConflict = local.revision !== result.revision;
          this.polishError = this.polishConflict
            ? '已恢复本地草稿，但服务器版本已改变。请复制保留草稿，再载入服务器版本核对。'
            : '已恢复未提交的本地草稿，请核对后点击保存。';
        }
      } catch (error) {
        this.polishError = error.status === 401 ? '请点击本页的“登录账号”，登录后再载入润色稿。' : `润色稿读取失败：${error.message}`;
      }
    },
    async reloadPolishFromServer() {
      if (this.polishSaving || this.polishResetting) return;
      if (this.polishDirty && !confirm('这会放弃本地草稿并载入服务器版本。请先复制保留需要的内容。继续吗？')) return;
      localStorage.removeItem(this.polishDraftKey());
      this.polishDirty = false;
      this.polishConflict = false;
      await this.loadPolish();
    },
    fillPolishFromTranslation() {
      this.polishData = {...this.buildPolishDraftFromTranslation(), summary: ''};
      this.polishDirty = false;
    },
    async resetPolishFromTranslation() {
      if (this.polishResetting || !this.polishReady || this.polishConflict) return;
      if (!confirm('删除服务器上的润色稿，并恢复为原译文？此操作成功后该稿不再计入夜间学习。')) return;
      this.polishResetting = true;
      clearTimeout(this.polishSaveTimer);
      try {
        if (this.polishSavePromise) await this.polishSavePromise;
        if (this.polishConflict || this.polishError && !this.polishReady) throw new Error('请先处理保存冲突或读取错误。');
        if (this.polishRevision !== null) await ServerAPI.request(this.polishEndpoint(), {method: 'DELETE', body: JSON.stringify({url: this.article.url, expected_revision: this.polishRevision})});
        localStorage.removeItem(this.polishDraftKey());
        this.fillPolishFromTranslation();
        this.polishRevision = null;
        this.polishExists = false;
        this.polishSavedAt = '';
        this.polishStatus = '润色';
        this.polishError = '';
        this.flash('润色记录已删除');
      } catch (error) {
        if (error.status === 409) this.polishConflict = true;
        this.polishError = `重置失败，草稿已保留：${error.message}`;
      } finally { this.polishResetting = false; }
    },
    openPolish() { this.mode = 'polish'; },
    onPolishInput() {
      this.polishDirty = true;
      this.polishEditVersion++;
      this.rememberPolishDraft();
      clearTimeout(this.polishSaveTimer);
      if (!this.polishConflict) this.polishSaveTimer = setTimeout(() => this.savePolish(false), 3000);
    },
    async savePolish(manual) {
      if (this.polishSaving) return this.polishSavePromise;
      if (!this.polishReady || this.polishConflict || this.polishResetting) return;
      clearTimeout(this.polishSaveTimer);
      this.polishSaving = true;
      this.polishError = '';
      this.polishSavePromise = (async () => {
        try {
          do {
            const version = this.polishEditVersion;
            const draft = {...this.polishData};
            const result = await ServerAPI.request(this.polishEndpoint(), {method: 'PUT', body: JSON.stringify({
              url: this.article.url, expected_revision: this.polishRevision,
              title: draft.title || '', subtitle: draft.subtitle || '', summary: draft.summary || '', body: draft.body || ''
            })});
            this.polishRevision = result.revision;
            this.polishExists = true;
            this.polishStatus = '已润色';
            this.polishSavedAt = this.fmtTime(result.draft.updated_at || new Date().toISOString());
            this.polishDirty = version !== this.polishEditVersion;
            if (this.polishDirty) this.rememberPolishDraft();
            else localStorage.removeItem(this.polishDraftKey());
          } while (this.polishDirty && !this.polishResetting);
          if (manual && !this.polishDirty) this.flash('润色已保存');
        } catch (error) {
          this.polishDirty = true;
          this.polishConflict = error.status === 409;
          this.polishError = this.polishConflict
            ? '服务器稿件已改变，已保留本地草稿。请复制需要的内容，再载入服务器版本核对。'
            : `保存未确认，本地草稿已保留：${error.message}`;
          this.rememberPolishDraft();
        } finally { this.polishSaving = false; this.polishSavePromise = null; }
      })();
      return this.polishSavePromise;
    },
    translationBase() {
      if (!this.translationSnapshot) throw new Error('请登录并重新载入文章后编辑。');
      return this.translationSnapshot;
    },
    async writeTranslation(path, content, message) {
      if (this.translationWriting) throw new Error('上一项译文修改正在保存，请稍后再试。');
      const snapshot = this.translationBase();
      this.translationWriting = true;
      try {
        await GH.putFile(path, content, message, {expectedSha: snapshot.sha});
        const hash = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(content));
        this.translationSnapshot = {content, sha: Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, '0')).join('')};
      } finally { this.translationWriting = false; }
    }
  };
}
