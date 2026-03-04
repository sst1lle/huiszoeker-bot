from flask import Flask, request, redirect, jsonify
import json, os, uuid

app = Flask(__name__)
USERS_DIR = '/app/data/users'
os.makedirs(USERS_DIR, exist_ok=True)

def laad_users():
    users = {}
    if os.path.exists(USERS_DIR):
        for f in os.listdir(USERS_DIR):
            if f.endswith('.json'):
                uid = f.replace('.json', '')
                with open(os.path.join(USERS_DIR, f)) as fp:
                    users[uid] = json.load(fp)
    return users

def sla_user_op(uid, data):
    os.makedirs(USERS_DIR, exist_ok=True)
    with open(os.path.join(USERS_DIR, f'{uid}.json'), 'w') as f:
        json.dump(data, f, indent=2)

def verwijder_user(uid):
    path = os.path.join(USERS_DIR, f'{uid}.json')
    if os.path.exists(path):
        os.remove(path)

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/api/users', methods=['GET'])
def get_users():
    return jsonify(laad_users())

@app.route('/api/users', methods=['POST'])
def add_user():
    data = request.json
    uid = str(uuid.uuid4())[:8]
    user = {
        'naam': data.get('naam', ''),
        'telegram_username': data.get('telegram_username', ''),
        'stad': data.get('stad', 'den-haag'),
        'min_prijs': int(data.get('min_prijs', 0)),
        'max_prijs': int(data.get('max_prijs', 1500)),
    }
    sla_user_op(uid, user)
    return jsonify({'id': uid, **user})

@app.route('/api/users/<uid>', methods=['PUT'])
def update_user(uid):
    data = request.json
    user = {
        'naam': data.get('naam', ''),
        'telegram_username': data.get('telegram_username', ''),
        'stad': data.get('stad', 'den-haag'),
        'min_prijs': int(data.get('min_prijs', 0)),
        'max_prijs': int(data.get('max_prijs', 1500)),
    }
    sla_user_op(uid, user)
    return jsonify({'id': uid, **user})

@app.route('/api/users/<uid>', methods=['DELETE'])
def delete_user(uid):
    verwijder_user(uid)
    return jsonify({'ok': True})

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Huiszoeker</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');
</style>
<style>
  :root {
    --ink: #1a1a2e;
    --paper: #f5f0e8;
    --accent: #c84b31;
    --accent2: #e8a87c;
    --muted: #8a8070;
    --card: #faf7f2;
    --border: #e0d8cc;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--paper);
    color: var(--ink);
    font-family: 'DM Sans', sans-serif;
    min-height: 100vh;
    background-image:
      radial-gradient(ellipse at 20% 0%, rgba(200,75,49,0.06) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 100%, rgba(232,168,124,0.08) 0%, transparent 50%);
  }
  .serif { font-family: 'DM Serif Display', serif; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(26,26,46,0.06), 0 0 0 1px rgba(255,255,255,0.6) inset;
  }
  .btn-primary {
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-family: 'DM Sans', sans-serif;
    font-weight: 500;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.15s ease;
    letter-spacing: 0.01em;
  }
  .btn-primary:hover { background: #b03d25; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(200,75,49,0.3); }
  .btn-ghost {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 16px;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
  .btn-danger {
    background: transparent;
    color: #c84b31;
    border: 1px solid rgba(200,75,49,0.3);
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-danger:hover { background: rgba(200,75,49,0.08); }
  input, select {
    width: 100%;
    background: white;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    color: var(--ink);
    outline: none;
    transition: border-color 0.15s;
  }
  input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(200,75,49,0.1); }
  label { font-size: 12px; font-weight: 500; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; display: block; margin-bottom: 6px; }
  .user-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    transition: all 0.2s;
    animation: slideIn 0.3s ease;
  }
  .user-card:hover { border-color: var(--accent2); box-shadow: 0 4px 16px rgba(26,26,46,0.08); }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .tag {
    display: inline-block;
    background: rgba(200,75,49,0.1);
    color: var(--accent);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.03em;
  }
  .divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 24px 0;
  }
  .modal-overlay {
    position: fixed; inset: 0;
    background: rgba(26,26,46,0.5);
    backdrop-filter: blur(4px);
    z-index: 50;
    display: flex; align-items: center; justify-content: center;
    opacity: 0; pointer-events: none;
    transition: opacity 0.2s;
  }
  .modal-overlay.active { opacity: 1; pointer-events: all; }
  .modal {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px;
    width: 100%; max-width: 480px;
    box-shadow: 0 24px 48px rgba(26,26,46,0.2);
    transform: translateY(16px);
    transition: transform 0.2s;
  }
  .modal-overlay.active .modal { transform: translateY(0); }
  .toast {
    position: fixed; bottom: 24px; right: 24px;
    background: var(--ink);
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14px;
    z-index: 100;
    transform: translateY(80px);
    opacity: 0;
    transition: all 0.3s ease;
  }
  .toast.show { transform: translateY(0); opacity: 1; }
  .empty-state {
    text-align: center;
    padding: 48px 24px;
    color: var(--muted);
  }
  .stat-pill {
    background: white;
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--muted);
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
</style>
</head>
<body>

<!-- HEADER -->
<header style="border-bottom: 1px solid var(--border); background: rgba(245,240,232,0.8); backdrop-filter: blur(8px); position: sticky; top: 0; z-index: 40;">
  <div style="max-width: 900px; margin: 0 auto; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: baseline; gap: 12px;">
      <h1 class="serif" style="font-size: 24px; line-height: 1;">Huiszoeker</h1>
      <span style="font-size: 12px; color: var(--muted);">woningbot</span>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <div class="stat-pill">
        <span style="width: 6px; height: 6px; background: #22c55e; border-radius: 50%; display: inline-block; animation: pulse 2s infinite;"></span>
        <span id="status-text">actief</span>
      </div>
      <button class="btn-primary" onclick="openModal()">+ Gebruiker toevoegen</button>
    </div>
  </div>
</header>

<style>
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>

<!-- MAIN -->
<main style="max-width: 900px; margin: 0 auto; padding: 40px 24px;">

  <!-- HERO -->
  <div style="margin-bottom: 40px;">
    <p class="serif" style="font-size: 42px; line-height: 1.15; max-width: 520px;">
      Jouw persoonlijke<br><em style="color: var(--accent);">woningwachter</em>
    </p>
    <p style="margin-top: 12px; color: var(--muted); font-size: 15px; max-width: 420px; line-height: 1.6;">
      Voeg gebruikers toe met hun eigen zoekvoorkeuren. De bot controleert Pararius elke 15 minuten en stuurt een Telegram-bericht bij nieuwe woningen.
    </p>
  </div>

  <!-- USERS GRID -->
  <div style="margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between;">
    <h2 style="font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);">
      Actieve gebruikers <span id="user-count" style="color: var(--accent);">0</span>
    </h2>
  </div>

  <div id="users-grid" style="display: flex; flex-direction: column; gap: 12px;">
    <div class="empty-state" id="empty-state">
      <div style="font-size: 32px; margin-bottom: 12px;">🏠</div>
      <p style="font-size: 15px; font-weight: 500; margin-bottom: 6px;">Nog geen gebruikers</p>
      <p style="font-size: 13px;">Voeg een gebruiker toe om te beginnen met zoeken.</p>
    </div>
  </div>

</main>

<!-- MODAL -->
<div class="modal-overlay" id="modal-overlay" onclick="closeModalOnOverlay(event)">
  <div class="modal">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <h2 class="serif" style="font-size: 22px;" id="modal-title">Gebruiker toevoegen</h2>
      <button onclick="closeModal()" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:20px;line-height:1;">✕</button>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <input type="hidden" id="edit-uid">

      <div>
        <label>Naam</label>
        <input type="text" id="form-naam" placeholder="bijv. Jan">
      </div>

      <div>
        <label>Telegram chat_id</label>
        <input type="text" id="form-telegram" placeholder="bijv. 1497723745">
      </div>

      <hr class="divider" style="margin: 4px 0;">

      <div>
        <label>Regio / Stad</label>
        <input type="text" id="form-stad" placeholder="bijv. den-haag, amsterdam, rotterdam">
        <p style="font-size: 11px; color: var(--muted); margin-top: 5px;">Gebruik de URL-notatie van Pararius (kleine letters, koppeltekens)</p>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div>
          <label>Min prijs (€)</label>
          <input type="number" id="form-min" placeholder="0" min="0" step="50">
        </div>
        <div>
          <label>Max prijs (€)</label>
          <input type="number" id="form-max" placeholder="1500" min="0" step="50">
        </div>
      </div>
    </div>

    <div style="display: flex; gap: 10px; margin-top: 24px; justify-content: flex-end;">
      <button class="btn-ghost" onclick="closeModal()">Annuleren</button>
      <button class="btn-primary" onclick="saveUser()">Opslaan</button>
    </div>
  </div>
</div>

<!-- TOAST -->
<div class="toast" id="toast"></div>


<script>
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('open-modal-btn').addEventListener('click', function() {
    openModal();
  });
  loadUsers();
});

let editingUid = null;

async function loadUsers() {
  const res = await fetch('/api/users');
  const users = await res.json();
  renderUsers(users);
}

function renderUsers(users) {
  const grid = document.getElementById('users-grid');
  const empty = document.getElementById('empty-state');
  const count = document.getElementById('user-count');
  const entries = Object.entries(users);

  count.textContent = entries.length;

  if (entries.length === 0) {
    empty.style.display = 'block';
    // Remove all user cards
    grid.querySelectorAll('.user-card').forEach(c => c.remove());
    return;
  }

  empty.style.display = 'none';
  grid.querySelectorAll('.user-card').forEach(c => c.remove());

  entries.forEach(([uid, u]) => {
    const card = document.createElement('div');
    card.className = 'user-card';
    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--accent2),var(--accent));display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:14px;">
            ${(u.naam || '?')[0].toUpperCase()}
          </div>
          <div>
            <div style="font-weight:600;font-size:15px;">${u.naam || 'Naamloos'}</div>
            <div style="font-size:13px;color:var(--muted);">chat_id: ${u.telegram_username || 'niet ingesteld'}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span class="tag">📍 ${u.stad}</span>
          <span class="tag">€${u.min_prijs} – €${u.max_prijs}</span>
          <button class="btn-ghost" style="padding:5px 12px;font-size:12px;" onclick="editUser('${uid}', ${JSON.stringify(u).replace(/"/g, '&quot;')})">Bewerken</button>
          <button class="btn-danger" onclick="deleteUser('${uid}', '${u.naam}')">Verwijderen</button>
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
}

function openModal(uid = null, user = null) {
  editingUid = uid;
  document.getElementById('modal-title').textContent = uid ? 'Gebruiker bewerken' : 'Gebruiker toevoegen';
  document.getElementById('form-naam').value = user?.naam || '';
  document.getElementById('form-telegram').value = user?.telegram_username || '';
  document.getElementById('form-stad').value = user?.stad || 'den-haag';
  document.getElementById('form-min').value = user?.min_prijs ?? 0;
  document.getElementById('form-max').value = user?.max_prijs ?? 1500;
  document.getElementById('modal-overlay').classList.add('active');
  setTimeout(() => document.getElementById('form-naam').focus(), 100);
}

function editUser(uid, user) {
  openModal(uid, user);
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('active');
  editingUid = null;
}

function closeModalOnOverlay(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}

async function saveUser() {
  const data = {
    naam: document.getElementById('form-naam').value.trim(),
    telegram_username: document.getElementById('form-telegram').value.trim(),
    stad: document.getElementById('form-stad').value.trim() || 'den-haag',
    min_prijs: parseInt(document.getElementById('form-min').value) || 0,
    max_prijs: parseInt(document.getElementById('form-max').value) || 1500,
  };

  if (!data.naam) {
    document.getElementById('form-naam').focus();
    showToast('Vul een naam in');
    return;
  }
  if (!data.telegram_username) {
    document.getElementById('form-telegram').focus();
    showToast('Vul een Telegram username in');
    return;
  }

  let res;
  if (editingUid) {
    res = await fetch(`/api/users/${editingUid}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
  } else {
    res = await fetch('/api/users', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
  }

  if (res.ok) {
    closeModal();
    loadUsers();
    showToast(editingUid ? '✅ Opgeslagen' : '✅ Gebruiker toegevoegd');
  }
}

async function deleteUser(uid, naam) {
  if (!confirm(`${naam} verwijderen?`)) return;
  await fetch(`/api/users/${uid}`, { method: 'DELETE' });
  loadUsers();
  showToast('Gebruiker verwijderd');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// Keyboard shortcut
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

</script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
