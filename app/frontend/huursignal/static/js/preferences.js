function toggleActive(lbl) {
  setTimeout(() => lbl.classList.toggle('active', lbl.querySelector('input').checked), 0);
}

async function savePref(redirectTo) {
  const types = [...document.querySelectorAll('#types input:checked')].map(x => x.value);
  const body = {
    naam:             document.getElementById('naam').value.trim(),
    telegram_chat_id: document.getElementById('telegram').value.trim(),
    stad:             document.getElementById('stad').value.trim().toLowerCase().replace(/ /g, '-'),
    min_prijs:        parseInt(document.getElementById('min_prijs').value) || 0,
    max_prijs:        parseInt(document.getElementById('max_prijs').value) || 1500,
    type_woning:      types,
    gewenste_wijken:  [...document.querySelectorAll('.wijk-cb:checked')].map(x => x.value),
  };
  document.getElementById('err').style.display = 'none';
  const r = await fetch('/api/preferences', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (d.ok) {
    if (redirectTo) {
      location.href = redirectTo;
    } else {
      const ok = document.getElementById('ok');
      ok.style.display = 'block';
      setTimeout(() => { ok.style.display = 'none'; }, 3000);
    }
  } else {
    const err = document.getElementById('err');
    err.textContent = d.error || 'Opslaan mislukt';
    err.style.display = 'block';
  }
}

// Herlaad de wijken-selector wanneer de stad verandert (live via /api/wijken).
// Behoudt reeds aangevinkte wijken.
async function laadWijken() {
  const container = document.getElementById('wijken-container');
  if (!container) return;
  const stadVal = document.getElementById('stad').value.trim().toLowerCase().replace(/ /g, '-');
  const steden = stadVal.split(',').map(s => s.trim()).filter(Boolean);
  const gekozen = new Set([...document.querySelectorAll('.wijk-cb:checked')].map(x => x.value));
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

  if (!steden.length) {
    container.innerHTML = '<p class="hint">Vul een stad in en sla op om wijken te kiezen.</p>';
    return;
  }
  container.innerHTML = '<p class="hint">Wijken laden…</p>';
  const blokken = [];
  for (const stad of steden) {
    let wijken = [];
    try {
      const r = await fetch(`/api/wijken?stad=${encodeURIComponent(stad)}`);
      wijken = (await r.json()).wijken || [];
    } catch (e) { /* stil — lege lijst */ }
    const tags = wijken.map(w => {
      const on = gekozen.has(w);
      return `<label class="${on ? 'active' : ''}" onclick="toggleActive(this)">`
           + `<input type="checkbox" class="wijk-cb" value="${esc(w)}" ${on ? 'checked' : ''} style="pointer-events:none"> ${esc(w)}</label>`;
    }).join('');
    blokken.push(`<div class="wijk-stad" data-stad="${esc(stad)}"><p class="hint" style="margin:8px 0 4px">${esc(stad)}</p>`
               + `<div class="checks">${tags || '<span class="hint">geen wijken gevonden</span>'}</div></div>`);
  }
  container.innerHTML = blokken.join('');
}

document.addEventListener('DOMContentLoaded', () => {
  const stadEl = document.getElementById('stad');
  if (stadEl) stadEl.addEventListener('change', laadWijken);
});
