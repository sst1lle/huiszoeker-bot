function toggleActive(lbl) {
  setTimeout(() => lbl.classList.toggle('active', lbl.querySelector('input').checked), 0);
}

function closeModal() {
  document.getElementById('editModal').classList.remove('open');
}

function openEdit(btn) {
  const u = JSON.parse(btn.dataset.user);
  document.getElementById('edit-uid').value      = u.uid;
  document.getElementById('edit-email').value    = u.email;
  document.getElementById('edit-naam').value     = u.naam;
  document.getElementById('edit-stad').value     = u.stad || '';
  document.getElementById('edit-min').value      = u.min_prijs;
  document.getElementById('edit-max').value      = u.max_prijs;
  document.getElementById('edit-telegram').value = u.telegram_chat_id;
  document.getElementById('edit-err').style.display = 'none';
  document.querySelectorAll('#edit-types input').forEach(cb => {
    cb.checked = u.type_woning.includes(cb.value);
    cb.closest('label').classList.toggle('active', cb.checked);
  });
  document.getElementById('editModal').classList.add('open');
}

async function saveEdit() {
  const uid   = document.getElementById('edit-uid').value;
  const types = [...document.querySelectorAll('#edit-types input:checked')].map(x => x.value);
  const body  = {
    email:            document.getElementById('edit-email').value.trim(),
    naam:             document.getElementById('edit-naam').value.trim(),
    stad:             document.getElementById('edit-stad').value.trim().toLowerCase().replace(/ /g, '-'),
    min_prijs:        parseInt(document.getElementById('edit-min').value) || 0,
    max_prijs:        parseInt(document.getElementById('edit-max').value) || 1500,
    telegram_chat_id: document.getElementById('edit-telegram').value.trim(),
    type_woning:      types,
  };
  const r = await fetch(`/api/admin/users/${uid}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (d.ok) {
    location.reload();
  } else {
    const err = document.getElementById('edit-err');
    err.textContent = d.error || 'Opslaan mislukt';
    err.style.display = 'block';
  }
}

async function confirmDelete(btn) {
  const naam = btn.dataset.naam || 'deze gebruiker';
  if (!confirm(`Account van ${naam} permanent verwijderen? Dit verwijdert ook alle voorkeuren en notificaties.`)) return;
  const r = await fetch(`/api/admin/users/${btn.dataset.uid}`, { method: 'DELETE' });
  const d = await r.json();
  if (d.ok) location.reload();
  else alert(d.error || 'Verwijderen mislukt');
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('editModal').addEventListener('click', e => {
    if (e.target === document.getElementById('editModal')) closeModal();
  });
});
