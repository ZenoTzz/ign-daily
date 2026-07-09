(function () {
  const CONFIG_URL = 'data/site-compliance.json';

  function clean(value) {
    return String(value || '').trim();
  }

  function externalLink(href) {
    const link = document.createElement('a');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }

  function addText(parent, text) {
    const span = document.createElement('span');
    span.textContent = text;
    parent.appendChild(span);
    return span;
  }

  function renderComplianceFooter(config) {
    if (document.querySelector('.site-compliance-footer')) return;

    const icpNumber = clean(config.icpNumber);
    const icpUrl = clean(config.icpUrl) || 'https://beian.miit.gov.cn/';
    const mpsNumber = clean(config.mpsNumber);
    const mpsUrl = clean(config.mpsUrl);
    const mpsIcon = clean(config.mpsIcon);
    const copyright = clean(config.copyright);

    if (!icpNumber && !mpsNumber && !copyright) return;

    const footer = document.createElement('footer');
    footer.className = 'site-compliance-footer';
    footer.setAttribute('aria-label', '备案信息');

    const inner = document.createElement('div');
    inner.className = 'site-compliance-inner';

    if (copyright) addText(inner, copyright);

    if (icpNumber) {
      const icp = externalLink(icpUrl);
      icp.textContent = icpNumber;
      inner.appendChild(icp);
    }

    if (mpsNumber) {
      const mps = mpsUrl ? externalLink(mpsUrl) : document.createElement('span');
      mps.className = 'site-compliance-mps';
      if (mpsIcon) {
        const icon = document.createElement('img');
        icon.src = mpsIcon;
        icon.alt = '';
        icon.loading = 'lazy';
        mps.appendChild(icon);
      }
      const text = document.createElement('span');
      text.textContent = mpsNumber;
      mps.appendChild(text);
      inner.appendChild(mps);
    }

    footer.appendChild(inner);
    document.body.appendChild(footer);
  }

  async function loadComplianceConfig() {
    try {
      const res = await fetch(`${CONFIG_URL}?t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) return {};
      const data = await res.json();
      return data && typeof data === 'object' ? data : {};
    } catch (_) {
      return {};
    }
  }

  async function initComplianceFooter() {
    const config = await loadComplianceConfig();
    renderComplianceFooter(config);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initComplianceFooter);
  } else {
    initComplianceFooter();
  }
})();
