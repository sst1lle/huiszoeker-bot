from flask import Flask, request, jsonify
import json, os, uuid

app = Flask(__name__)
USERS_DIR = os.environ.get('USERS_DIR', './data/users')
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
        'telegram_chat_id': data.get('telegram_chat_id', ''),
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
        'telegram_chat_id': data.get('telegram_chat_id', ''),
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

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="nl" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Huursignal</title>
<style>
:root {
  --bg:         #ffffff;
  --bg-2:       #f7f7f5;
  --bg-3:       #efeeeb;
  --border:     #e3e2de;
  --border-2:   #d3d1cb;
  --text:       #1a1a1a;
  --text-2:     #6b6b6b;
  --text-3:     #999999;
  --accent:     #e8632a;
  --accent-h:   #d4521a;
  --accent-s:   rgba(232,99,42,0.12);
  --shadow-sm:  0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md:  0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-lg:  0 16px 40px rgba(0,0,0,0.12), 0 4px 8px rgba(0,0,0,0.06);
  --radius:     10px;
  --radius-sm:  6px;
  --radius-lg:  14px;
  --t:          0.15s ease;
}
[data-theme="dark"] {
  --bg:         #1f1f1f;
  --bg-2:       #2a2a2a;
  --bg-3:       #333333;
  --border:     #3a3a3a;
  --border-2:   #4a4a4a;
  --text:       #f0f0f0;
  --text-2:     #a0a0a0;
  --text-3:     #666666;
  --accent:     #f07340;
  --accent-h:   #e8632a;
  --accent-s:   rgba(240,115,64,0.15);
  --shadow-sm:  0 1px 3px rgba(0,0,0,0.3);
  --shadow-md:  0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg:  0 16px 40px rgba(0,0,0,0.5);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 14px; line-height: 1.5; min-height: 100vh;
  transition: background var(--t), color var(--t);
  -webkit-font-smoothing: antialiased;
}
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-thumb { background: var(--border-2); border-radius: 3px; }
.container { max-width: 700px; margin: 0 auto; padding: 0 24px; }

/* TOPBAR */
.topbar {
  position: sticky; top: 0; z-index: 100;
  border-bottom: 1px solid var(--border);
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: background var(--t), border-color var(--t);
}
[data-theme="dark"] .topbar { background: rgba(31,31,31,0.85); }
.topbar-inner { display: flex; align-items: center; justify-content: space-between; height: 52px; }
.logo { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; color: var(--text); text-decoration: none; }
.logo-icon { width: 28px; height: 28px; border-radius: 7px; background: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 14px; }
.topbar-right { display: flex; align-items: center; gap: 8px; }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 6px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 500; cursor: pointer; transition: all var(--t); border: none; font-family: inherit; white-space: nowrap; }
.btn:active { transform: scale(0.97); }
.btn-primary { background: var(--accent); color: #fff; padding: 7px 14px; box-shadow: 0 1px 2px rgba(232,99,42,0.3); }
.btn-primary:hover { background: var(--accent-h); box-shadow: 0 2px 6px rgba(232,99,42,0.4); }
.btn-ghost { background: transparent; color: var(--text-2); padding: 7px 12px; border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--bg-2); color: var(--text); border-color: var(--border-2); }
.btn-danger { background: transparent; color: var(--text-3); padding: 5px 10px; font-size: 12px; border: 1px solid transparent; border-radius: var(--radius-sm); }
.btn-danger:hover { background: rgba(220,38,38,0.08); color: #dc2626; border-color: rgba(220,38,38,0.2); }
.theme-btn { width: 32px; height: 32px; border-radius: var(--radius-sm); background: transparent; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 15px; transition: all var(--t); color: var(--text-2); }
.theme-btn:hover { background: var(--bg-2); color: var(--text); }

/* STATUS */
.status-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); background: var(--bg-2); border: 1px solid var(--border); border-radius: 20px; padding: 4px 10px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; animation: pulse 2.5s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:1; box-shadow: 0 0 0 0 rgba(34,197,94,0.4); } 50% { opacity:0.7; box-shadow: 0 0 0 4px rgba(34,197,94,0); } }

/* MAIN */
.main { padding: 36px 0 80px; }
.page-header { margin-bottom: 28px; }
.page-title { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
.page-sub { font-size: 13px; color: var(--text-2); margin-top: 3px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-3); display: flex; align-items: center; gap: 6px; }
.count { background: var(--bg-3); color: var(--text-2); font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 20px; border: 1px solid var(--border); }

/* CARDS */
.cards { display: flex; flex-direction: column; gap: 8px; }
.card {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 14px 16px; display: flex; align-items: center; gap: 14px;
  transition: all var(--t); box-shadow: var(--shadow-sm);
  animation: fadeUp 0.2s ease both;
}
.card:hover { border-color: var(--border-2); box-shadow: var(--shadow-md); transform: translateY(-1px); }
@keyframes fadeUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
.avatar { width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; color: #fff; }
.card-info { flex: 1; min-width: 0; }
.card-name { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-meta { display: flex; align-items: center; gap: 6px; margin-top: 3px; flex-wrap: wrap; }
.tag { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; font-weight: 500; color: var(--text-2); background: var(--bg-2); border: 1px solid var(--border); border-radius: 5px; padding: 2px 7px; }
.tag-accent { color: var(--accent); background: var(--accent-s); border-color: rgba(232,99,42,0.2); }
.card-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

/* EMPTY */
.empty { text-align: center; padding: 56px 24px; border: 1px dashed var(--border-2); border-radius: var(--radius-lg); background: var(--bg-2); }
.empty-icon { font-size: 28px; margin-bottom: 12px; opacity: 0.4; }
.empty-title { font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 4px; }
.empty-sub { font-size: 13px; color: var(--text-3); }

/* MODAL */
.overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.4); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 24px; opacity: 0; pointer-events: none; transition: opacity 0.2s; }
.overlay.open { opacity: 1; pointer-events: all; }
.modal { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 24px; width: 100%; max-width: 440px; box-shadow: var(--shadow-lg); transform: translateY(12px) scale(0.98); transition: transform 0.2s; }
.overlay.open .modal { transform: translateY(0) scale(1); }
.modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.modal-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
.close-btn { width: 28px; height: 28px; border-radius: 6px; background: var(--bg-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 14px; color: var(--text-2); transition: all var(--t); }
.close-btn:hover { background: var(--bg-3); color: var(--text); }

/* FORM */
.form-group { margin-bottom: 14px; }
.form-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 5px; }
.form-input { width: 100%; background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 11px; font-size: 14px; color: var(--text); font-family: inherit; outline: none; transition: all var(--t); }
.form-input::placeholder { color: var(--text-3); }
.form-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-s); background: var(--bg); }
.form-hint { font-size: 11px; color: var(--text-3); margin-top: 4px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.divider { border: none; border-top: 1px solid var(--border); margin: 18px 0; }
.form-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }

/* TOAST */
.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(80px); background: var(--text); color: var(--bg); font-size: 13px; font-weight: 500; padding: 10px 16px; border-radius: var(--radius); box-shadow: var(--shadow-lg); z-index: 300; transition: transform 0.3s cubic-bezier(0.34,1.56,0.64,1), opacity 0.3s; opacity: 0; white-space: nowrap; }
.toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }
</style>
</head>
<body>

<header class="topbar">
  <div class="container topbar-inner">
    <a class="logo" href="/">
      <div class="logo-icon">🏠</div>
      Huursignal
    </a>
    <div class="topbar-right">
      <div class="status-pill">
        <span class="status-dot"></span>
        actief
      </div>
      <button class="theme-btn" id="theme-btn">🌙</button>
      <button class="btn btn-primary" id="add-btn">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1v10M1 6h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        Gebruiker
      </button>
    </div>
  </div>
</header>

<main class="main">
  <div class="container">
    <div class="page-header">
      <h1 class="page-title">Gebruikers</h1>
      <p class="page-sub">Beheer wie notificaties ontvangt en met welke zoekcriteria.</p>
    </div>

    <div class="section-header">
      <span class="section-label">
        Actief
        <span class="count" id="count">0</span>
      </span>
    </div>

    <div class="cards" id="cards">
      <div class="empty" id="empty">
        <div class="empty-icon">👤</div>
        <div class="empty-title">Geen gebruikers</div>
        <div class="empty-sub">Voeg een gebruiker toe om te beginnen.</div>
      </div>
    </div>
  </div>
</main>

<!-- MODAL -->
<div class="overlay" id="overlay">
  <div class="modal">
    <div class="modal-header">
      <h2 class="modal-title" id="modal-title">Gebruiker toevoegen</h2>
      <button class="close-btn" id="close-btn">✕</button>
    </div>

    <div class="form-group">
      <label class="form-label">Naam</label>
      <input class="form-input" type="text" id="f-naam" placeholder="bijv. Jan">
    </div>
    <div class="form-group">
      <label class="form-label">Telegram chat_id</label>
      <input class="form-input" type="text" id="f-telegram" placeholder="bijv. 1497723745">
      <div class="form-hint">Stuur /start naar je bot → haal chat_id op via getUpdates</div>
    </div>
    <hr class="divider">
    <div class="form-group">
      <label class="form-label">Stad / Regio</label>
      <input class="form-input" type="text" id="f-stad" placeholder="bijv. den-haag">
      <div class="form-hint">Pararius URL-notatie: kleine letters en koppeltekens</div>
    </div>
    <div class="form-row">
      <div class="form-group" style="margin:0">
        <label class="form-label">Min prijs (€)</label>
        <input class="form-input" type="number" id="f-min" placeholder="0" min="0" step="50">
      </div>
      <div class="form-group" style="margin:0">
        <label class="form-label">Max prijs (€)</label>
        <input class="form-input" type="number" id="f-max" placeholder="1500" min="0" step="50">
      </div>
    </div>
    <div class="form-footer">
      <button class="btn btn-ghost" id="cancel-btn">Annuleren</button>
      <button class="btn btn-primary" id="save-btn">Opslaan</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// Theme
const html = document.documentElement;
const themeBtn = document.getElementById('theme-btn');
function setTheme(dark) {
  html.setAttribute('data-theme', dark ? 'dark' : 'light');
  themeBtn.textContent = dark ? '☀️' : '🌙';
  localStorage.setItem('theme', dark ? 'dark' : 'light');
}
const saved = localStorage.getItem('theme');
setTheme(saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches);
themeBtn.addEventListener('click', () => setTheme(html.getAttribute('data-theme') !== 'dark'));

// State
let editUid = null;

// API
async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined
  });
  return res.json();
}

// Avatar colors
function avatarBg(name) {
  const colors = ['#e8632a','#f5a623','#27ae60','#2980b9','#8e44ad','#e74c3c'];
  let h = 0;
  for (let c of name) h = (h * 31 + c.charCodeAt(0)) & 0xffffffff;
  return colors[Math.abs(h) % colors.length];
}

// Render
async function loadUsers() {
  const users = await api('GET', '/api/users');
  const entries = Object.entries(users);
  const cards = document.getElementById('cards');
  const empty = document.getElementById('empty');
  document.getElementById('count').textContent = entries.length;
  cards.querySelectorAll('.card').forEach(c => c.remove());

  if (!entries.length) { empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  entries.forEach(([uid, u], i) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.style.animationDelay = i * 40 + 'ms';
    const letter = (u.naam || '?')[0].toUpperCase();
    const color = avatarBg(u.naam || uid);
    card.innerHTML = `
      <div class="avatar" style="background:linear-gradient(135deg,${color},${color}bb)">${letter}</div>
      <div class="card-info">
        <div class="card-name">${u.naam || 'Naamloos'}</div>
        <div class="card-meta">
          <span class="tag">📍 ${u.stad}</span>
          <span class="tag tag-accent">€${u.min_prijs} – €${u.max_prijs}</span>
          <span class="tag">💬 ${u.telegram_chat_id || '—'}</span>
        </div>
      </div>
      <div class="card-actions">
        <button class="btn btn-ghost" style="padding:5px 10px;font-size:12px" onclick='editUser("${uid}",${JSON.stringify(u).replace(/'/g,"&#39;")})'>Bewerken</button>
        <button class="btn btn-danger" onclick="deleteUser('${uid}','${u.naam}')">Verwijder</button>
      </div>`;
    cards.appendChild(card);
  });
}

// Modal
function openModal(uid, u) {
  editUid = uid || null;
  document.getElementById('modal-title').textContent = uid ? 'Gebruiker bewerken' : 'Gebruiker toevoegen';
  document.getElementById('f-naam').value = u?.naam || '';
  document.getElementById('f-telegram').value = u?.telegram_chat_id || '';
  document.getElementById('f-stad').value = u?.stad || 'den-haag';
  document.getElementById('f-min').value = u?.min_prijs ?? 0;
  document.getElementById('f-max').value = u?.max_prijs ?? 1500;
  document.getElementById('overlay').classList.add('open');
  setTimeout(() => document.getElementById('f-naam').focus(), 150);
}

function editUser(uid, u) { openModal(uid, u); }

function closeModal() {
  document.getElementById('overlay').classList.remove('open');
  editUid = null;
}

async function saveUser() {
  const naam = document.getElementById('f-naam').value.trim();
  const telegram = document.getElementById('f-telegram').value.trim();
  if (!naam) { toast('Vul een naam in'); document.getElementById('f-naam').focus(); return; }
  if (!telegram) { toast('Vul een Telegram chat_id in'); document.getElementById('f-telegram').focus(); return; }

  const data = {
    naam, telegram_chat_id: telegram,
    stad: document.getElementById('f-stad').value.trim() || 'den-haag',
    min_prijs: parseInt(document.getElementById('f-min').value) || 0,
    max_prijs: parseInt(document.getElementById('f-max').value) || 1500,
  };

  if (editUid) {
    await api('PUT', `/api/users/${editUid}`, data);
    toast('✓ Opgeslagen');
  } else {
    await api('POST', '/api/users', data);
    toast('✓ Gebruiker toegevoegd');
  }
  closeModal();
  loadUsers();
}

async function deleteUser(uid, naam) {
  if (!confirm(`${naam} verwijderen?`)) return;
  await api('DELETE', `/api/users/${uid}`);
  toast('Verwijderd');
  loadUsers();
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2800);
}

// Events
document.getElementById('add-btn').addEventListener('click', () => openModal());
document.getElementById('close-btn').addEventListener('click', closeModal);
document.getElementById('cancel-btn').addEventListener('click', closeModal);
document.getElementById('save-btn').addEventListener('click', saveUser);
document.getElementById('overlay').addEventListener('click', e => { if (e.target.id === 'overlay') closeModal(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'Enter' && document.getElementById('overlay').classList.contains('open')) saveUser();
});

loadUsers();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false') == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
