from flask import Flask, request, jsonify, session
import json, os, uuid, hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'huursignal-secret-change-me')

USERS_DIR = os.environ.get('USERS_DIR', './data/users')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')
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

def is_admin():
    return session.get('admin') == True

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Verkeerd wachtwoord'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('admin', None)
    return jsonify({'ok': True})

@app.route('/api/session')
def check_session():
    return jsonify({'admin': is_admin()})

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
    if not is_admin():
        return jsonify({'error': 'Niet ingelogd als admin'}), 403
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
    if not is_admin():
        return jsonify({'error': 'Niet ingelogd als admin'}), 403
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

.topbar {
  position: sticky; top: 0; z-index: 100;
  border-bottom: 1px solid var(--border);
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  transition: background var(--t), border-color var(--t);
}
[data-theme="dark"] .topbar { background: rgba(31,31,31,0.85); }
.topbar-inner { display: flex; align-items: center; justify-content: space-between; height: 52px; }
.logo { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; color: var(--text); text-decoration: none; }
.logo-icon { width: 28px; height: 28px; border-radius: 7px; background: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 14px; }
.topbar-right { display: flex; align-items: center; gap: 8px; }

.btn { display: inline-flex; align-items: center; gap: 6px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 500; cursor: pointer; transition: all var(--t); border: none; font-family: inherit; white-space: nowrap; }
.btn:active { transform: scale(0.97); }
.btn-primary { background: var(--accent); color: #fff; padding: 7px 14px; box-shadow: 0 1px 2px rgba(232,99,42,0.3); }
.btn-primary:hover { background: var(--accent-h); box-shadow: 0 2px 6px rgba(232,99,42,0.4); }
.btn-ghost { background: transparent; color: var(--text-2); padding: 7px 12px; border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--bg-2); color: var(--text); border-color: var(--border-2); }
.btn-danger { background: transparent; color: var(--text-3); padding: 5px 10px; font-size: 12px; border: 1px solid transparent; border-radius: var(--radius-sm); }
.btn-danger:hover { background: rgba(220,38,38,0.08); color: #dc2626; border-color: rgba(220,38,38,0.2); }
.theme-btn { width: 32px; height: 32px; border-radius: var(--radius-sm); background: transparent; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 15px; transition: all var(--t); color: var(--text-2); }
.theme-btn:hover { background: var(--bg-2); }

.status-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); background: var(--bg-2); border: 1px solid var(--border); border-radius: 20px; padding: 4px 10px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; animation: blink 2.5s ease-in-out infinite; }
@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

/* ADMIN BADGE */
.admin-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-s); border: 1px solid rgba(232,99,42,0.25); border-radius: 20px; padding: 3px 10px; }

.main { padding: 36px 0 80px; }
.page-header { margin-bottom: 28px; }
.page-title { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
.page-sub { font-size: 13px; color: var(--text-2); margin-top: 3px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-3); display: flex; align-items: center; gap: 6px; }
.count { background: var(--bg-3); color: var(--text-2); font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 20px; border: 1px solid var(--border); }

.cards { display: flex; flex-direction: column; gap: 8px; }
.card { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; display: flex; align-items: center; gap: 14px; transition: all var(--t); box-shadow: var(--shadow-sm); animation: fadeUp 0.2s ease both; }
.card:hover { border-color: var(--border-2); box-shadow: var(--shadow-md); transform: translateY(-1px); }
@keyframes fadeUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
.avatar { width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; color: #fff; }
.card-info { flex: 1; min-width: 0; }
.card-name { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-meta { display: flex; align-items: center; gap: 6px; margin-top: 3px; flex-wrap: wrap; }
.tag { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; font-weight: 500; color: var(--text-2); background: var(--bg-2); border: 1px solid var(--border); border-radius: 5px; padding: 2px 7px; }
.tag-accent { color: var(--accent); background: var(--accent-s); border-color: rgba(232,99,42,0.2); }
.card-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

.empty { text-align: center; padding: 56px 24px; border: 1px dashed var(--border-2); border-radius: var(--radius-lg); background: var(--bg-2); }
.empty-icon { font-size: 28px; margin-bottom: 12px; opacity: 0.4; }
.empty-title { font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 4px; }
.empty-sub { font-size: 13px; color: var(--text-3); }

.overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.4); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 24px; opacity: 0; pointer-events: none; transition: opacity 0.2s; }
.overlay.open { opacity: 1; pointer-events: all; }
.modal { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 24px; width: 100%; max-width: 440px; box-shadow: var(--shadow-lg); transform: translateY(12px) scale(0.98); transition: transform 0.2s; }
.overlay.open .modal { transform: translateY(0) scale(1); }
.modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.modal-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
.close-btn { width: 28px; height: 28px; border-radius: 6px; background: var(--bg-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 14px; color: var(--text-2); transition: all var(--t); }
.close-btn:hover { background: var(--bg-3); }

.form-group { margin-bottom: 14px; }
.form-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 5px; }
.form-input { width: 100%; background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 11px; font-size: 14px; color: var(--text); font-family: inherit; outline: none; transition: all var(--t); }
.form-input::placeholder { color: var(--text-3); }
.form-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-s); background: var(--bg); }
.form-hint { font-size: 11px; color: var(--text-3); margin-top: 4px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.divider { border: none; border-top: 1px solid var(--border); margin: 18px 0; }
.form-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }

.step-dot { height: 4px; flex: 1; border-radius: 2px; background: var(--border-2); transition: background 0.2s; }
.step-dot.active { background: var(--accent); }
.step-icon { width: 44px; height: 44px; border-radius: 12px; background: var(--accent-s); border: 1px solid rgba(232,99,42,0.2); display: flex; align-items: center; justify-content: center; font-size: 22px; margin-bottom: 14px; }
.step-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 8px; }
.step-body { font-size: 13px; color: var(--text-2); line-height: 1.7; }
.step-body strong { color: var(--text); }
.step-code { background: var(--bg-3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 12px; font-family: monospace; font-size: 13px; color: var(--accent); margin: 8px 0; display: block; }
.step-link { color: var(--accent); text-decoration: none; font-weight: 500; }
.step-link:hover { text-decoration: underline; }
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
      <span class="admin-badge" id="admin-badge" style="display:none">🔑 Admin</span>
      <button class="theme-btn" id="theme-btn">🌙</button>
      <button class="btn btn-ghost" id="admin-btn">Inloggen</button>
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
      <span class="section-label">Actief <span class="count" id="count">0</span></span>
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

<!-- GEBRUIKER MODAL -->
<div class="overlay" id="overlay">
  <div class="modal">
    <div class="modal-header">
      <div style="display:flex;align-items:center;gap:8px;">
        <h2 class="modal-title" id="modal-title">Gebruiker toevoegen</h2>
        <button class="theme-btn" id="help-btn" title="Hoe werkt het?" style="width:22px;height:22px;font-size:12px;border-radius:50%;flex-shrink:0;">?</button>
      </div>
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

<!-- LOGIN MODAL -->
<div class="overlay" id="login-overlay">
  <div class="modal" style="max-width:360px">
    <div class="modal-header">
      <h2 class="modal-title">Admin inloggen</h2>
      <button class="close-btn" id="login-close">✕</button>
    </div>
    <div class="form-group">
      <label class="form-label">Wachtwoord</label>
      <input class="form-input" type="password" id="f-password" placeholder="••••••••">
      <div class="form-hint" id="login-error" style="color:#dc2626;display:none">Verkeerd wachtwoord</div>
    </div>
    <div class="form-footer">
      <button class="btn btn-ghost" id="login-cancel">Annuleren</button>
      <button class="btn btn-primary" id="login-submit">Inloggen</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- CONFIRM TELEGRAM MODAL -->
<div class="overlay" id="confirm-overlay">
  <div class="modal" style="max-width:380px">
    <div class="modal-header">
      <h2 class="modal-title">Telegram ingesteld?</h2>
      <button class="close-btn" id="confirm-close">✕</button>
    </div>
    <p style="font-size:14px;color:var(--text-2);line-height:1.6;margin-bottom:20px;">Heb je je Telegram bot al opgezet en je chat_id ingevuld? Zonder dit ontvang je geen meldingen.</p>
    <div style="display:flex;gap:10px;">
      <button class="btn btn-ghost" style="flex:1;justify-content:center" id="confirm-no">Nee, laat me zien hoe</button>
      <button class="btn btn-primary" style="flex:1;justify-content:center" id="confirm-yes">Ja, opslaan!</button>
    </div>
  </div>
</div>

<!-- ONBOARDING MODAL -->
<div class="overlay" id="onboarding-overlay">
  <div class="modal" style="max-width:480px">
    <div class="modal-header">
      <h2 class="modal-title" id="onboarding-title">Stap 1 van 3</h2>
      <button class="close-btn" id="onboarding-close">✕</button>
    </div>

    <!-- Progress bar -->
    <div style="display:flex;gap:6px;margin-bottom:24px;">
      <div class="step-dot active" id="dot-1"></div>
      <div class="step-dot" id="dot-2"></div>
      <div class="step-dot" id="dot-3"></div>
    </div>

    <!-- Step content -->
    <div id="onboarding-content"></div>

    <div style="display:flex;justify-content:space-between;margin-top:24px;padding-top:16px;border-top:1px solid var(--border);">
      <button class="btn btn-ghost" id="onboarding-back">Terug</button>
      <button class="btn btn-primary" id="onboarding-next">Volgende →</button>
    </div>
  </div>
</div>

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
let isAdmin = false;

// API
async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined
  });
  return res.json();
}

// Admin status
async function checkAdmin() {
  const data = await api('GET', '/api/session');
  isAdmin = data.admin;
  document.getElementById('admin-badge').style.display = isAdmin ? 'inline-flex' : 'none';
  document.getElementById('admin-btn').textContent = isAdmin ? 'Uitloggen' : 'Inloggen';
  loadUsers();
}

// Avatar
function avatarBg(name) {
  const colors = ['#e8632a','#f5a623','#27ae60','#2980b9','#8e44ad','#e74c3c'];
  let h = 0;
  for (let c of name) h = (h * 31 + c.charCodeAt(0)) & 0xffffffff;
  return colors[Math.abs(h) % colors.length];
}

// Render users
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

    // Admin knoppen alleen tonen als ingelogd
    const adminActions = isAdmin ? `
      <button class="btn btn-ghost" style="padding:5px 10px;font-size:12px" onclick='editUser("${uid}",${JSON.stringify(u).replace(/'/g,"&#39;")})'>Bewerken</button>
      <button class="btn btn-danger" onclick="deleteUser('${uid}','${u.naam}')">Verwijder</button>
    ` : '';

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
      <div class="card-actions">${adminActions}</div>`;
    cards.appendChild(card);
  });
}

// Gebruiker modal
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
function closeModal() { document.getElementById('overlay').classList.remove('open'); editUid = null; }

// saveUser moved to doSaveUser below

async function deleteUser(uid, naam) {
  if (!confirm(`${naam} verwijderen?`)) return;
  const res = await api('DELETE', `/api/users/${uid}`);
  if (res.error) { toast('Niet ingelogd als admin'); return; }
  toast('Verwijderd'); loadUsers();
}

// Login modal
function openLogin() { document.getElementById('login-overlay').classList.add('open'); setTimeout(() => document.getElementById('f-password').focus(), 150); }
function closeLogin() { document.getElementById('login-overlay').classList.remove('open'); document.getElementById('f-password').value = ''; document.getElementById('login-error').style.display = 'none'; }

async function doLogin() {
  const pw = document.getElementById('f-password').value;
  const res = await api('POST', '/api/login', { password: pw });
  if (res.ok) {
    isAdmin = true;
    closeLogin();
    toast('✓ Ingelogd als admin');
    // Onboarding steps content
const steps = [
  {
    icon: '🤖',
    title: 'Bot zoeken in Telegram',
    body: `
      <p>Open Telegram en zoek naar jouw bot via de zoekbalk bovenin.</p>
      <span class="step-code">@mijn_huiszoeker_bot</span>
      <p>Klik op de bot en druk op <strong>Start</strong> of stuur het commando:</p>
      <span class="step-code">/start</span>
      <p>De bot bevestigt nu dat hij je herkent. Zonder dit kan hij je geen berichten sturen!</p>
    `
  },
  {
    icon: '🔑',
    title: 'Jouw chat_id ophalen',
    body: `
      <p>Zoek in Telegram naar de bot <strong>@userinfobot</strong> en stuur <strong>/start</strong>.</p>
      <span class="step-code">@userinfobot</span>
      <p>De bot stuurt je meteen je eigen info terug, zo:</p>
      <div style="background:var(--bg-3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px;margin:10px 0;font-size:13px;line-height:1.8;">
        Id: <strong style="color:var(--accent)">123456789</strong><br>
        @jouwusername
      </div>
      <p>Kopieer het getal achter <strong>Id:</strong> — dat is jouw chat_id.</p>
    `
  },
  {
    icon: '📝',
    title: 'Formulier invullen',
    body: `
      <p>Klik op <strong>+ Gebruiker</strong> en vul het formulier in:</p>
      <ul style="margin:10px 0 10px 16px;display:flex;flex-direction:column;gap:6px">
        <li><strong>Naam</strong> — jouw naam of bijnaam</li>
        <li><strong>Telegram chat_id</strong> — het getal uit stap 2</li>
        <li><strong>Stad</strong> — bijv. <code style="background:var(--bg-3);padding:1px 5px;border-radius:3px">den-haag</code></li>
        <li><strong>Min/max prijs</strong> — jouw prijsrange</li>
      </ul>
      <p>Druk op <strong>Opslaan</strong> — de bot stuurt je meteen een melding zodra er een nieuwe woning verschijnt!</p>
    `
  }
];

let currentStep = 0;
let pendingSave = false;

function renderStep(n) {
  const step = steps[n];
  document.getElementById('onboarding-title').textContent = `Stap ${n+1} van 3`;
  document.getElementById('onboarding-content').innerHTML = `
    <div class="step-icon">${step.icon}</div>
    <div class="step-title">${step.title}</div>
    <div class="step-body">${step.body}</div>
  `;
  [0,1,2].forEach(i => {
    document.getElementById('dot-'+(i+1)).className = 'step-dot' + (i === n ? ' active' : '');
  });
  document.getElementById('onboarding-back').style.visibility = n === 0 ? 'hidden' : 'visible';
  document.getElementById('onboarding-next').textContent = n === 2 ? (pendingSave ? 'Klaar, opslaan!' : 'Klaar!') : 'Volgende →';
}

function openOnboarding(fromSave = false) {
  pendingSave = fromSave;
  currentStep = 0;
  renderStep(0);
  document.getElementById('onboarding-overlay').classList.add('open');
  // Close confirm modal if open
  document.getElementById('confirm-overlay').classList.remove('open');
}

function closeOnboarding() {
  document.getElementById('onboarding-overlay').classList.remove('open');
}

document.getElementById('help-btn').addEventListener('click', () => openOnboarding(false));
document.getElementById('onboarding-close').addEventListener('click', closeOnboarding);
document.getElementById('onboarding-overlay').addEventListener('click', e => { if (e.target.id === 'onboarding-overlay') closeOnboarding(); });

document.getElementById('onboarding-next').addEventListener('click', () => {
  if (currentStep < 2) {
    currentStep++;
    renderStep(currentStep);
  } else {
    closeOnboarding();
    if (pendingSave) doSaveUser();
  }
});

document.getElementById('onboarding-back').addEventListener('click', () => {
  if (currentStep > 0) { currentStep--; renderStep(currentStep); }
});

// Confirm modal
function openConfirm() {
  document.getElementById('confirm-overlay').classList.add('open');
}
function closeConfirm() {
  document.getElementById('confirm-overlay').classList.remove('open');
}

document.getElementById('confirm-close').addEventListener('click', closeConfirm);
document.getElementById('confirm-overlay').addEventListener('click', e => { if (e.target.id === 'confirm-overlay') closeConfirm(); });
document.getElementById('confirm-yes').addEventListener('click', () => { closeConfirm(); doSaveUser(); });
document.getElementById('confirm-no').addEventListener('click', () => openOnboarding(true));

// Rename saveUser to doSaveUser (actual save logic)
// saveUser now shows confirm first
const doSaveUser = async function() {
  const naam = document.getElementById('f-naam').value.trim();
  const telegram = document.getElementById('f-telegram').value.trim();
  if (!naam) { toast('Vul een naam in'); return; }
  if (!telegram) { toast('Vul een Telegram chat_id in'); return; }
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
  closeModal(); loadUsers();
};

checkAdmin();
  } else {
    document.getElementById('login-error').style.display = 'block';
  }
}

async function doLogout() {
  await api('POST', '/api/logout');
  isAdmin = false;
  toast('Uitgelogd');
  // Onboarding steps content
const steps = [
  {
    icon: '🤖',
    title: 'Bot zoeken in Telegram',
    body: `
      <p>Open Telegram en zoek naar jouw bot via de zoekbalk bovenin.</p>
      <span class="step-code">@mijn_huiszoeker_bot</span>
      <p>Klik op de bot en druk op <strong>Start</strong> of stuur het commando:</p>
      <span class="step-code">/start</span>
      <p>De bot bevestigt nu dat hij je herkent. Zonder dit kan hij je geen berichten sturen!</p>
    `
  },
  {
    icon: '🔑',
    title: 'Jouw chat_id ophalen',
    body: `
      <p>Zoek in Telegram naar de bot <strong>@userinfobot</strong> en stuur <strong>/start</strong>.</p>
      <span class="step-code">@userinfobot</span>
      <p>De bot stuurt je meteen je eigen info terug, zo:</p>
      <div style="background:var(--bg-3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px;margin:10px 0;font-size:13px;line-height:1.8;">
        Id: <strong style="color:var(--accent)">123456789</strong><br>
        @jouwusername
      </div>
      <p>Kopieer het getal achter <strong>Id:</strong> — dat is jouw chat_id.</p>
    `
  },
  {
    icon: '📝',
    title: 'Formulier invullen',
    body: `
      <p>Klik op <strong>+ Gebruiker</strong> en vul het formulier in:</p>
      <ul style="margin:10px 0 10px 16px;display:flex;flex-direction:column;gap:6px">
        <li><strong>Naam</strong> — jouw naam of bijnaam</li>
        <li><strong>Telegram chat_id</strong> — het getal uit stap 2</li>
        <li><strong>Stad</strong> — bijv. <code style="background:var(--bg-3);padding:1px 5px;border-radius:3px">den-haag</code></li>
        <li><strong>Min/max prijs</strong> — jouw prijsrange</li>
      </ul>
      <p>Druk op <strong>Opslaan</strong> — de bot stuurt je meteen een melding zodra er een nieuwe woning verschijnt!</p>
    `
  }
];

let currentStep = 0;
let pendingSave = false;

function renderStep(n) {
  const step = steps[n];
  document.getElementById('onboarding-title').textContent = `Stap ${n+1} van 3`;
  document.getElementById('onboarding-content').innerHTML = `
    <div class="step-icon">${step.icon}</div>
    <div class="step-title">${step.title}</div>
    <div class="step-body">${step.body}</div>
  `;
  [0,1,2].forEach(i => {
    document.getElementById('dot-'+(i+1)).className = 'step-dot' + (i === n ? ' active' : '');
  });
  document.getElementById('onboarding-back').style.visibility = n === 0 ? 'hidden' : 'visible';
  document.getElementById('onboarding-next').textContent = n === 2 ? (pendingSave ? 'Klaar, opslaan!' : 'Klaar!') : 'Volgende →';
}

function openOnboarding(fromSave = false) {
  pendingSave = fromSave;
  currentStep = 0;
  renderStep(0);
  document.getElementById('onboarding-overlay').classList.add('open');
  // Close confirm modal if open
  document.getElementById('confirm-overlay').classList.remove('open');
}

function closeOnboarding() {
  document.getElementById('onboarding-overlay').classList.remove('open');
}

document.getElementById('help-btn').addEventListener('click', () => openOnboarding(false));
document.getElementById('onboarding-close').addEventListener('click', closeOnboarding);
document.getElementById('onboarding-overlay').addEventListener('click', e => { if (e.target.id === 'onboarding-overlay') closeOnboarding(); });

document.getElementById('onboarding-next').addEventListener('click', () => {
  if (currentStep < 2) {
    currentStep++;
    renderStep(currentStep);
  } else {
    closeOnboarding();
    if (pendingSave) doSaveUser();
  }
});

document.getElementById('onboarding-back').addEventListener('click', () => {
  if (currentStep > 0) { currentStep--; renderStep(currentStep); }
});

// Confirm modal
function openConfirm() {
  document.getElementById('confirm-overlay').classList.add('open');
}
function closeConfirm() {
  document.getElementById('confirm-overlay').classList.remove('open');
}

document.getElementById('confirm-close').addEventListener('click', closeConfirm);
document.getElementById('confirm-overlay').addEventListener('click', e => { if (e.target.id === 'confirm-overlay') closeConfirm(); });
document.getElementById('confirm-yes').addEventListener('click', () => { closeConfirm(); doSaveUser(); });
document.getElementById('confirm-no').addEventListener('click', () => openOnboarding(true));

// Rename saveUser to doSaveUser (actual save logic)
// saveUser now shows confirm first
const doSaveUser = async function() {
  const naam = document.getElementById('f-naam').value.trim();
  const telegram = document.getElementById('f-telegram').value.trim();
  if (!naam) { toast('Vul een naam in'); return; }
  if (!telegram) { toast('Vul een Telegram chat_id in'); return; }
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
  closeModal(); loadUsers();
};

checkAdmin();
}

// Admin knop toggle
document.getElementById('admin-btn').addEventListener('click', () => {
  if (isAdmin) doLogout();
  else openLogin();
});

// Events
document.getElementById('add-btn').addEventListener('click', () => openModal());
document.getElementById('close-btn').addEventListener('click', closeModal);
document.getElementById('cancel-btn').addEventListener('click', closeModal);
document.getElementById('save-btn').addEventListener('click', () => {
  const naam = document.getElementById('f-naam').value.trim();
  const telegram = document.getElementById('f-telegram').value.trim();
  if (!naam) { toast('Vul een naam in'); return; }
  if (!telegram) { toast('Vul een Telegram chat_id in'); return; }
  // Only show confirm for new users, not when editing
  if (!editUid) {
    openConfirm();
  } else {
    doSaveUser();
  }
});
document.getElementById('login-close').addEventListener('click', closeLogin);
document.getElementById('login-cancel').addEventListener('click', closeLogin);
document.getElementById('login-submit').addEventListener('click', doLogin);

document.getElementById('overlay').addEventListener('click', e => { if (e.target.id === 'overlay') closeModal(); });
document.getElementById('login-overlay').addEventListener('click', e => { if (e.target.id === 'login-overlay') closeLogin(); });

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeLogin(); }
  if (e.key === 'Enter') {
    if (document.getElementById('overlay').classList.contains('open')) { if (!editUid) openConfirm(); else doSaveUser(); }
    if (document.getElementById('login-overlay').classList.contains('open')) doLogin();
  }
});

// Onboarding steps content
const steps = [
  {
    icon: '🤖',
    title: 'Bot zoeken in Telegram',
    body: `
      <p>Open Telegram en zoek naar jouw bot via de zoekbalk bovenin.</p>
      <span class="step-code">@mijn_huiszoeker_bot</span>
      <p>Klik op de bot en druk op <strong>Start</strong> of stuur het commando:</p>
      <span class="step-code">/start</span>
      <p>De bot bevestigt nu dat hij je herkent. Zonder dit kan hij je geen berichten sturen!</p>
    `
  },
  {
    icon: '🔑',
    title: 'Jouw chat_id ophalen',
    body: `
      <p>Zoek in Telegram naar de bot <strong>@userinfobot</strong> en stuur <strong>/start</strong>.</p>
      <span class="step-code">@userinfobot</span>
      <p>De bot stuurt je meteen je eigen info terug, zo:</p>
      <div style="background:var(--bg-3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px;margin:10px 0;font-size:13px;line-height:1.8;">
        @jouwusername<br>
        Id: <strong style="color:var(--accent)">123456789</strong>
      </div>
      <p>Kopieer het getal achter <strong>Id:</strong> — dat is jouw chat_id.</p>
    `
  },
  {
    icon: '📝',
    title: 'Formulier invullen',
    body: `
      <p>Klik op <strong>+ Gebruiker</strong> en vul het formulier in:</p>
      <ul style="margin:10px 0 10px 16px;display:flex;flex-direction:column;gap:6px">
        <li><strong>Naam</strong> — jouw naam of bijnaam</li>
        <li><strong>Telegram chat_id</strong> — het getal uit stap 2</li>
        <li><strong>Stad</strong> — bijv. <code style="background:var(--bg-3);padding:1px 5px;border-radius:3px">den-haag</code></li>
        <li><strong>Min/max prijs</strong> — jouw prijsrange</li>
      </ul>
      <p>Druk op <strong>Opslaan</strong> — de bot stuurt je meteen een melding zodra er een nieuwe woning verschijnt!</p>
    `
  }
];

let currentStep = 0;
let pendingSave = false;

function renderStep(n) {
  const step = steps[n];
  document.getElementById('onboarding-title').textContent = `Stap ${n+1} van 3`;
  document.getElementById('onboarding-content').innerHTML = `
    <div class="step-icon">${step.icon}</div>
    <div class="step-title">${step.title}</div>
    <div class="step-body">${step.body}</div>
  `;
  [0,1,2].forEach(i => {
    document.getElementById('dot-'+(i+1)).className = 'step-dot' + (i === n ? ' active' : '');
  });
  document.getElementById('onboarding-back').style.visibility = n === 0 ? 'hidden' : 'visible';
  document.getElementById('onboarding-next').textContent = n === 2 ? (pendingSave ? 'Klaar, opslaan!' : 'Klaar!') : 'Volgende →';
}

function openOnboarding(fromSave = false) {
  pendingSave = fromSave;
  currentStep = 0;
  renderStep(0);
  document.getElementById('onboarding-overlay').classList.add('open');
  // Close confirm modal if open
  document.getElementById('confirm-overlay').classList.remove('open');
}

function closeOnboarding() {
  document.getElementById('onboarding-overlay').classList.remove('open');
}

document.getElementById('help-btn').addEventListener('click', () => openOnboarding(false));
document.getElementById('onboarding-close').addEventListener('click', closeOnboarding);
document.getElementById('onboarding-overlay').addEventListener('click', e => { if (e.target.id === 'onboarding-overlay') closeOnboarding(); });

document.getElementById('onboarding-next').addEventListener('click', () => {
  if (currentStep < 2) {
    currentStep++;
    renderStep(currentStep);
  } else {
    closeOnboarding();
    if (pendingSave) doSaveUser();
  }
});

document.getElementById('onboarding-back').addEventListener('click', () => {
  if (currentStep > 0) { currentStep--; renderStep(currentStep); }
});

// Confirm modal
function openConfirm() {
  document.getElementById('confirm-overlay').classList.add('open');
}
function closeConfirm() {
  document.getElementById('confirm-overlay').classList.remove('open');
}

document.getElementById('confirm-close').addEventListener('click', closeConfirm);
document.getElementById('confirm-overlay').addEventListener('click', e => { if (e.target.id === 'confirm-overlay') closeConfirm(); });
document.getElementById('confirm-yes').addEventListener('click', () => { closeConfirm(); doSaveUser(); });
document.getElementById('confirm-no').addEventListener('click', () => openOnboarding(true));

// Rename saveUser to doSaveUser (actual save logic)
// saveUser now shows confirm first
const doSaveUser = async function() {
  const naam = document.getElementById('f-naam').value.trim();
  const telegram = document.getElementById('f-telegram').value.trim();
  if (!naam) { toast('Vul een naam in'); return; }
  if (!telegram) { toast('Vul een Telegram chat_id in'); return; }
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
  closeModal(); loadUsers();
};

checkAdmin();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false') == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
