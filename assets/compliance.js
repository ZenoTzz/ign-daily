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
    const icpNumber = clean(config.icpNumber);
    const icpUrl = clean(config.icpUrl) || 'https://beian.miit.gov.cn/';
    const mpsNumber = clean(config.mpsNumber);
    const mpsUrl = clean(config.mpsUrl);
    const mpsIcon = clean(config.mpsIcon);
    const copyright = clean(config.copyright);

    if (!icpNumber && !mpsNumber && !copyright) return;

    let footer = document.querySelector('.site-compliance-footer');
    let inner = footer ? footer.querySelector('.site-compliance-inner') : null;
    if (!footer) {
      footer = document.createElement('footer');
      footer.className = 'site-compliance-footer';
      footer.setAttribute('aria-label', '备案信息');
      inner = document.createElement('div');
      inner.className = 'site-compliance-inner';
      footer.appendChild(inner);
      document.body.appendChild(footer);
    }
    if (!inner) return;

    if (copyright && !inner.querySelector('[data-compliance="copyright"]')) {
      const copy = addText(inner, copyright);
      copy.dataset.compliance = 'copyright';
    }

    if (icpNumber && !inner.querySelector('[data-compliance="icp"]')) {
      const icp = externalLink(icpUrl);
      icp.dataset.compliance = 'icp';
      icp.textContent = icpNumber;
      inner.appendChild(icp);
    }

    if (mpsNumber && !inner.querySelector('[data-compliance="mps"]')) {
      const mps = mpsUrl ? externalLink(mpsUrl) : document.createElement('span');
      mps.dataset.compliance = 'mps';
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
