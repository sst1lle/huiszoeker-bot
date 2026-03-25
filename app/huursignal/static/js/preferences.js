async function testTelegram() {
  const chatId = document.getElementById('telegram').value.trim();
  const status = document.getElementById('telegram-status');
  if (!chatId) {
    status.style.cssText = 'display:block;color:#b91c1c';
    status.textContent = 'Voer eerst een chat ID in';
    return;
  }
  status.style.cssText = 'display:block;color:var(--muted)';
  status.textContent = 'Bezig…';
  const r = await fetch('/api/telegram/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId }),
  });
  const d = await r.json();
  if (d.ok) {
    status.style.cssText = 'display:block;color:#166534';
    status.textContent = '✅ Setup correct! Testbericht verstuurd.';
  } else {
    status.style.cssText = 'display:block;color:#b91c1c';
    status.textContent = '❌ ' + (d.error || 'Versturen mislukt. Heb je /start gestuurd naar de bot?');
  }
}

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
    radius_km:        parseInt(document.getElementById('radius_km').value) || null,
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
