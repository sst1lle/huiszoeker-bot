import os
import functools
import requests as req
from datetime import datetime, timezone
from flask import Flask, render_template_string, redirect, url_for, request, session, jsonify
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

from db import get_db

load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY", "changeme")

WONING_TYPES = ["kamer", "appartement", "studio", "anti-kraak", "studentenwoning", "gemeubileerd"]


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def fmt_prijs(p):
    if not p:
        return "?"
    return "\u20ac\u00a0" + f"{p:,}".replace(",", ".")


# ── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f4f4f5; color: #18181b; line-height: 1.5; }
a { text-decoration: none; color: inherit; }

nav { background: #fff; border-bottom: 1px solid #e4e4e7; position: sticky; top: 0; z-index: 10; }
.nav-inner { max-width: 1120px; margin: 0 auto; padding: 0 20px;
             display: flex; align-items: center; justify-content: space-between; height: 56px; }
.logo { font-size: 17px; font-weight: 700; letter-spacing: -.3px; }
.logo span { color: #2563eb; }
.nav-links { display: flex; gap: 4px; align-items: center; }
.nav-links a { font-size: 14px; color: #52525b; padding: 6px 12px; border-radius: 6px; }
.nav-links a:hover { background: #f4f4f5; color: #18181b; }
.nav-links .btn-nav { background: #2563eb; color: #fff !important; }
.nav-links .btn-nav:hover { background: #1d4ed8; }

.container { max-width: 1120px; margin: 0 auto; padding: 0 20px; }
.page-head { padding: 28px 0 16px; }
.page-head h1 { font-size: 22px; font-weight: 700; }
.page-head p { color: #71717a; font-size: 14px; margin-top: 4px; }

.auth-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center;
             background: #f4f4f5; padding: 20px; }
.auth-card { background: #fff; border-radius: 12px; padding: 36px; width: 100%; max-width: 400px;
             box-shadow: 0 2px 12px rgba(0,0,0,.08); }
.auth-card h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.auth-card .sub { color: #71717a; font-size: 14px; margin-bottom: 28px; }

.field { margin-bottom: 16px; }
.field label { display: block; font-size: 13px; font-weight: 500; color: #3f3f46; margin-bottom: 5px; }
.field input { width: 100%; padding: 9px 12px; border: 1px solid #d4d4d8; border-radius: 7px;
               font-size: 14px; outline: none; transition: border-color .15s, box-shadow .15s; }
.field input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.1); }
.field .hint { font-size: 12px; color: #a1a1aa; margin-top: 4px; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

.checks { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.checks label { display: flex; align-items: center; gap: 6px; padding: 6px 12px;
                background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 6px;
                font-size: 13px; cursor: pointer; user-select: none; }
.checks label.active { background: #eff6ff; border-color: #93c5fd; color: #2563eb; }
.checks input[type=checkbox] { width: 14px; height: 14px; accent-color: #2563eb; }

.btn { display: inline-flex; align-items: center; justify-content: center;
       padding: 10px 18px; border-radius: 7px; font-size: 14px; font-weight: 500;
       cursor: pointer; border: none; transition: all .15s; }
.btn-primary { background: #2563eb; color: #fff; width: 100%; }
.btn-primary:hover { background: #1d4ed8; }
.btn-outline { background: #fff; color: #3f3f46; border: 1px solid #d4d4d8; }
.btn-outline:hover { background: #f4f4f5; }

.err { background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c;
       border-radius: 7px; padding: 10px 14px; font-size: 13px; margin-bottom: 14px; display: none; }
.ok  { background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534;
       border-radius: 7px; padding: 10px 14px; font-size: 13px; margin-bottom: 14px; display: none; }
.auth-foot { text-align: center; font-size: 13px; color: #71717a; margin-top: 20px; }
.auth-foot a { color: #2563eb; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 18px; padding-bottom: 40px; }
.card { background: #fff; border-radius: 10px; overflow: hidden;
        box-shadow: 0 1px 4px rgba(0,0,0,.07); transition: box-shadow .2s, transform .2s; }
.card:hover { box-shadow: 0 6px 20px rgba(0,0,0,.1); transform: translateY(-2px); }
.card-photo { width: 100%; height: 176px; object-fit: cover; display: block; }
.card-no-photo { width: 100%; height: 176px; background: linear-gradient(135deg,#e4e4e7,#d4d4d8);
                 display: flex; align-items: center; justify-content: center;
                 color: #a1a1aa; font-size: 36px; }
.card-body { padding: 14px 16px 16px; }
.card-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; }
.card-adres { font-size: 14px; font-weight: 600; line-height: 1.35; flex: 1; min-width: 0;
              overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px;
         margin-left: 8px; white-space: nowrap; flex-shrink: 0; }
.badge-pararius { background: #fff3e0; color: #c2410c; }
.badge-kamernet  { background: #ecfdf5; color: #065f46; }
.card-prijs { font-size: 19px; font-weight: 700; color: #2563eb; margin-bottom: 6px; }
.card-meta { font-size: 12px; color: #71717a; }
.card-link { display: inline-block; margin-top: 10px; font-size: 13px; color: #2563eb; }
.card-link:hover { text-decoration: underline; }

.pager { display: flex; gap: 6px; justify-content: center; padding: 16px 0 40px; flex-wrap: wrap; }
.pager a, .pager span { padding: 7px 13px; border-radius: 6px; font-size: 14px;
                         border: 1px solid #e4e4e7; background: #fff; color: #3f3f46; }
.pager a:hover { background: #f4f4f5; }
.pager .cur { background: #2563eb; color: #fff; border-color: #2563eb; }

.empty { text-align: center; padding: 64px 20px; grid-column: 1/-1; }
.empty .icon { font-size: 44px; margin-bottom: 14px; }
.empty h2 { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.empty p { color: #71717a; font-size: 14px; }
.empty a { color: #2563eb; }

.form-page { max-width: 580px; margin: 36px auto 60px; padding: 0 20px; }
.form-page h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.form-page .sub { color: #71717a; font-size: 14px; margin-bottom: 28px; }
.form-card { background: #fff; border-radius: 12px; padding: 28px;
             box-shadow: 0 1px 6px rgba(0,0,0,.07); }
.section-label { font-size: 12px; font-weight: 600; color: #a1a1aa; text-transform: uppercase;
                 letter-spacing: .6px; margin: 22px 0 10px; }
.section-label:first-child { margin-top: 0; }
.form-actions { display: flex; gap: 10px; margin-top: 24px; }

@media (max-width: 600px) {
  .grid { grid-template-columns: 1fr; }
  .row-2 { grid-template-columns: 1fr; }
  .auth-card { padding: 24px 20px; }
  .form-actions { flex-direction: column; }
  .nav-links a:not(.btn-nav) { display: none; }
}
"""


# ── Page wrapper ─────────────────────────────────────────────────────────────

def _page(title, body, nav=True):
    nav_html = ""
    if nav:
        nav_html = """
<nav>
  <div class="nav-inner">
    <a href="/dashboard" class="logo">Huur<span>signaal</span></a>
    <div class="nav-links">
      <a href="/dashboard">Woningen</a>
      <a href="/instellingen">Instellingen</a>
      <a href="#" onclick="doLogout()" class="btn-nav btn">Uitloggen</a>
    </div>
  </div>
</nav>
<script>
  async function doLogout() {
    await fetch('/api/logout', { method: 'POST' });
    location.href = '/';
  }
</script>"""
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} \u2014 Huursignaal</title>
  <style>{_CSS}</style>
</head>
<body>
{nav_html}
{body}
</body>
</html>"""


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/")
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    body = """
<div class="auth-wrap">
  <div class="auth-card">
    <h1>Inloggen</h1>
    <p class="sub">Welkom terug bij Huursignaal</p>
    <div class="err" id="err"></div>
    <div class="field">
      <label>E-mailadres</label>
      <input type="email" id="email" placeholder="jij@voorbeeld.nl" autocomplete="email">
    </div>
    <div class="field">
      <label>Wachtwoord</label>
      <input type="password" id="pwd" placeholder="&#9679;&#9679;&#9679;&#9679;&#9679;&#9679;&#9679;&#9679;" autocomplete="current-password">
    </div>
    <button class="btn btn-primary" onclick="doLogin()">Inloggen</button>
    <p class="auth-foot">Nog geen account? <a href="/register">Registreren</a> &nbsp;·&nbsp; <a href="/forgot-password">Wachtwoord vergeten</a></p>
  </div>
</div>
<script>
  document.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  async function doLogin() {
    const err = document.getElementById('err');
    err.style.display = 'none';
    const r = await fetch('/api/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ email: document.getElementById('email').value.trim(),
                             password: document.getElementById('pwd').value })
    });
    const d = await r.json();
    if (d.ok) location.href = '/dashboard';
    else { err.textContent = d.error || 'Inloggen mislukt'; err.style.display = 'block'; }
  }
</script>"""
    return _page("Inloggen", body, nav=False)


@app.route("/register")
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    body = """
<div class="auth-wrap">
  <div class="auth-card">
    <h1>Account aanmaken</h1>
    <p class="sub">Begin met zoeken naar je nieuwe woning</p>
    <div class="err" id="err"></div>
    <div class="field">
      <label>Naam</label>
      <input type="text" id="naam" placeholder="Je naam" autocomplete="name">
    </div>
    <div class="field">
      <label>E-mailadres</label>
      <input type="email" id="email" placeholder="jij@voorbeeld.nl" autocomplete="email">
    </div>
    <div class="field">
      <label>Wachtwoord</label>
      <input type="password" id="pwd" placeholder="Minimaal 6 tekens" autocomplete="new-password">
    </div>
    <button class="btn btn-primary" onclick="doRegister()">Account aanmaken</button>
    <p class="auth-foot">Al een account? <a href="/">Inloggen</a></p>
  </div>
</div>
<script>
  async function doRegister() {
    const err = document.getElementById('err');
    err.style.display = 'none';
    const r = await fetch('/api/register', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ naam: document.getElementById('naam').value.trim(),
                             email: document.getElementById('email').value.trim(),
                             password: document.getElementById('pwd').value })
    });
    const d = await r.json();
    if (d.ok) location.href = '/onboarding';
    else { err.textContent = d.error || 'Registratie mislukt'; err.style.display = 'block'; }
  }
</script>"""
    return _page("Registreren", body, nav=False)


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    try:
        db = get_db()
        result = db.auth.sign_in_with_password({"email": data["email"], "password": data["password"]})
        session["user_id"] = result.user.id
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False, "error": "E-mail of wachtwoord onjuist"}), 401


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}
    try:
        db = get_db()
        result = db.auth.sign_up({"email": data["email"], "password": data["password"]})
        if result.user:
            session["user_id"] = result.user.id
            session["naam"] = data.get("naam", "")
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Registratie mislukt"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/forgot-password")
def forgot_password():
    body = """
<div class="auth-wrap">
  <div class="auth-card">
    <h1>Wachtwoord vergeten</h1>
    <p class="sub">We sturen je een resetlink per e-mail</p>
    <div class="err" id="err"></div>
    <div class="ok"  id="ok"></div>
    <div class="field">
      <label>E-mailadres</label>
      <input type="email" id="email" placeholder="jij@voorbeeld.nl" autocomplete="email">
    </div>
    <button class="btn btn-primary" onclick="doForgot()">Verstuur resetlink</button>
    <p class="auth-foot"><a href="/">Terug naar inloggen</a></p>
  </div>
</div>
<script>
  document.addEventListener('keydown', e => { if (e.key === 'Enter') doForgot(); });
  async function doForgot() {
    const err = document.getElementById('err');
    const ok  = document.getElementById('ok');
    err.style.display = 'none'; ok.style.display = 'none';
    const r = await fetch('/api/forgot-password', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ email: document.getElementById('email').value.trim() })
    });
    const d = await r.json();
    if (d.ok) {
      ok.textContent = 'Als dit e-mailadres bekend is, ontvang je een resetlink.';
      ok.style.display = 'block';
    } else {
      err.textContent = d.error || 'Versturen mislukt';
      err.style.display = 'block';
    }
  }
</script>"""
    return _page("Wachtwoord vergeten", body, nav=False)


@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    import requests as req
    data = request.json or {}
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"ok": False, "error": "E-mailadres vereist"}), 400
    try:
        supabase_url = os.environ["SUPABASE_URL"]
        supabase_key = os.environ["SUPABASE_KEY"]
        req.post(
            f"{supabase_url}/auth/v1/recover",
            json={"email": email},
            params={"redirect_to": "https://huursignal.com/reset-password"},
            headers={"apikey": supabase_key, "Content-Type": "application/json"},
            timeout=10,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/reset-password", strict_slashes=False)
def reset_password():
    body = """
<div class="auth-wrap">
  <div class="auth-card">
    <h1>Nieuw wachtwoord</h1>
    <p class="sub">Kies een nieuw wachtwoord voor je account</p>
    <div class="err" id="err"></div>
    <div class="ok"  id="ok"></div>
    <div class="field">
      <label>Nieuw wachtwoord</label>
      <input type="password" id="pwd" placeholder="Minimaal 6 tekens" autocomplete="new-password">
    </div>
    <button class="btn btn-primary" onclick="doReset()">Wachtwoord instellen</button>
  </div>
</div>
<script>
  function getHashParam(key) {
    const hash = window.location.hash.substring(1);
    const params = Object.fromEntries(new URLSearchParams(hash));
    return params[key] || '';
  }
  async function doReset() {
    const err = document.getElementById('err');
    const ok  = document.getElementById('ok');
    err.style.display = 'none'; ok.style.display = 'none';
    const access_token   = getHashParam('access_token');
    const refresh_token  = getHashParam('refresh_token');
    const password       = document.getElementById('pwd').value;
    if (!access_token) {
      err.textContent = 'Ongeldige resetlink. Vraag een nieuwe aan.';
      err.style.display = 'block'; return;
    }
    const r = await fetch('/api/reset-password', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ access_token, refresh_token, password })
    });
    const d = await r.json();
    if (d.ok) {
      ok.textContent = 'Wachtwoord ingesteld! Je wordt doorgestuurd...';
      ok.style.display = 'block';
      setTimeout(() => location.href = '/', 2000);
    } else {
      err.textContent = d.error || 'Instellen mislukt';
      err.style.display = 'block';
    }
  }
</script>"""
    return _page("Wachtwoord instellen", body, nav=False)


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data = request.json or {}
    access_token  = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    password      = data.get("password", "")
    if not access_token or not password:
        return jsonify({"ok": False, "error": "Ongeldige aanvraag"}), 400
    try:
        db = get_db()
        db.auth.set_session(access_token, refresh_token)
        db.auth.update_user({"password": password})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Preferences form helper ───────────────────────────────────────────────────

def _pref_form(pref, submit_label, redirect_to):
    stad      = pref.get("stad", "") or ""
    min_prijs = pref.get("min_prijs", "") or ""
    max_prijs = pref.get("max_prijs", "") or ""
    telegram  = pref.get("telegram_chat_id", "") or ""
    naam      = pref.get("naam", "") or ""
    actieve   = pref.get("type_woning") or []

    checks = ""
    for t in WONING_TYPES:
        checked = "checked" if t in actieve else ""
        active_cls = "active" if t in actieve else ""
        checks += (f'<label class="{active_cls}" onclick="toggleActive(this)">'
                   f'<input type="checkbox" value="{t}" {checked} style="pointer-events:none"> {t}</label>')

    redir_js = f"location.href='{redirect_to}';" if redirect_to else (
        "const ok=document.getElementById('ok');ok.style.display='block';"
        "setTimeout(()=>ok.style.display='none',3000);"
    )

    return f"""
<div class="form-card">
  <div class="err" id="err"></div>
  <div class="ok"  id="ok">Opgeslagen!</div>
  <p class="section-label">Jouw gegevens</p>
  <div class="field">
    <label>Naam</label>
    <input type="text" id="naam" value="{naam}" placeholder="Je naam">
  </div>
  <div class="field">
    <label>Telegram chat ID <span style="font-weight:400;color:#a1a1aa">(optioneel)</span></label>
    <input type="text" id="telegram" value="{telegram}" placeholder="bijv. 1234567890">
    <p class="hint">Stuur /start naar @userinfobot om je chat ID te achterhalen</p>
  </div>
  <p class="section-label">Zoekvoorkeuren</p>
  <div class="field">
    <label>Stad</label>
    <input type="text" id="stad" value="{stad}" placeholder="bijv. den-haag">
    <p class="hint">Formaat: den-haag, amsterdam, rotterdam, utrecht</p>
  </div>
  <div class="row-2">
    <div class="field">
      <label>Min. huur (€/maand)</label>
      <input type="number" id="min_prijs" value="{min_prijs}" placeholder="0" min="0">
    </div>
    <div class="field">
      <label>Max. huur (€/maand)</label>
      <input type="number" id="max_prijs" value="{max_prijs}" placeholder="1500" min="0">
    </div>
  </div>
  <div class="field">
    <label>Type woning <span style="font-weight:400;color:#a1a1aa">(leeg = alles)</span></label>
    <div class="checks" id="types">{checks}</div>
  </div>
  <div class="form-actions">
    <button class="btn btn-primary" style="width:auto" onclick="savePref()">{submit_label}</button>
    <a href="/dashboard" class="btn btn-outline">Annuleren</a>
  </div>
</div>
<script>
  function toggleActive(lbl) {{
    setTimeout(() => lbl.classList.toggle('active', lbl.querySelector('input').checked), 0);
  }}
  async function savePref() {{
    const types = [...document.querySelectorAll('#types input:checked')].map(x => x.value);
    const body = {{
      naam:              document.getElementById('naam').value.trim(),
      telegram_chat_id:  document.getElementById('telegram').value.trim(),
      stad:              document.getElementById('stad').value.trim().toLowerCase().replace(/ /g,'-'),
      min_prijs:         parseInt(document.getElementById('min_prijs').value) || 0,
      max_prijs:         parseInt(document.getElementById('max_prijs').value) || 1500,
      type_woning:       types
    }};
    document.getElementById('err').style.display = 'none';
    const r = await fetch('/api/preferences', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)
    }});
    const d = await r.json();
    if (d.ok) {{ {redir_js} }}
    else {{
      const err = document.getElementById('err');
      err.textContent = d.error || 'Opslaan mislukt';
      err.style.display = 'block';
    }}
  }}
</script>"""


# ── Onboarding & instellingen ─────────────────────────────────────────────────

@app.route("/onboarding")
@login_required
def onboarding():
    naam = session.pop("naam", "")
    body = f"""
<div class="form-page">
  <h1>Zoekvoorkeuren instellen</h1>
  <p class="sub">Stel je criteria in. Je ontvangt Telegram-meldingen bij nieuwe passende woningen.</p>
  {_pref_form({"naam": naam}, "Opslaan en beginnen", "/dashboard")}
</div>"""
    return _page("Onboarding", body)


@app.route("/instellingen")
@login_required
def instellingen():
    db = get_db()
    result = db.table("user_preferences").select("*").eq("user_id", session["user_id"]).execute()
    pref = result.data[0] if result.data else {}
    body = f"""
<div class="form-page">
  <h1>Instellingen</h1>
  <p class="sub">Pas je zoekvoorkeuren en gegevens aan.</p>
  {_pref_form(pref, "Opslaan", "")}
</div>"""
    return _page("Instellingen", body)


@app.route("/api/preferences", methods=["POST"])
@login_required
def api_preferences():
    data = request.json or {}
    user_id = session["user_id"]
    db = get_db()

    pref_data = {
        "user_id":          user_id,
        "naam":             data.get("naam"),
        "telegram_chat_id": data.get("telegram_chat_id"),
        "stad":             data.get("stad"),
        "min_prijs":        data.get("min_prijs"),
        "max_prijs":        data.get("max_prijs"),
        "type_woning":      data.get("type_woning", []),
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    existing = db.table("user_preferences").select("id").eq("user_id", user_id).execute()
    if existing.data:
        db.table("user_preferences").update(pref_data).eq("user_id", user_id).execute()
    else:
        db.table("user_preferences").insert(pref_data).execute()

    return jsonify({"ok": True})


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    db = get_db()

    pref_result = db.table("user_preferences").select("*").eq("user_id", user_id).execute()
    pref = pref_result.data[0] if pref_result.data else None

    if not pref:
        return redirect(url_for("onboarding"))

    page     = request.args.get("page", 1, type=int)
    per_page = 20
    offset   = (page - 1) * per_page

    stad      = pref.get("stad", "")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types     = pref.get("type_woning") or []

    result = (db.table("listings")
              .select("*", count="exact")
              .eq("stad", stad)
              .eq("beschikbaar", True)
              .gte("prijs", min_prijs)
              .lte("prijs", max_prijs)
              .order("eerste_gezien", desc=True)
              .range(offset, offset + per_page - 1)
              .execute())

    raw    = result.data or []
    totaal = result.count or 0

    # Pararius heeft type_woning=None → altijd tonen
    listings = [l for l in raw
                if not (l.get("type_woning") and types and l["type_woning"] not in types)]

    totaal_paginas = max(1, (totaal + per_page - 1) // per_page)

    # ── Cards ──
    cards_html = ""
    for l in listings:
        foto   = l.get("foto_url") or ""
        adres  = l.get("adres") or "Onbekend adres"
        stad_l = l.get("stad") or ""
        prijs  = fmt_prijs(l.get("prijs"))
        opp    = l.get("oppervlakte")
        source = l.get("source", "")
        url    = l.get("url", "#")

        badge_cls  = "badge-pararius" if source == "pararius" else "badge-kamernet"
        badge_naam = "Pararius" if source == "pararius" else "Kamernet"
        meta       = f"{opp}\u00a0m\u00b2" if opp else ""
        foto_html  = (f'<img class="card-photo" src="{foto}" alt="" loading="lazy">'
                      if foto else '<div class="card-no-photo">\U0001f3e0</div>')

        cards_html += f"""
<div class="card">
  <a href="{url}" target="_blank" rel="noopener">{foto_html}</a>
  <div class="card-body">
    <div class="card-top">
      <div class="card-adres">{adres}{(", " + stad_l) if stad_l else ""}</div>
      <span class="badge {badge_cls}">{badge_naam}</span>
    </div>
    <div class="card-prijs">{prijs}<span style="font-size:13px;font-weight:400;color:#71717a">/maand</span></div>
    {('<div class="card-meta">' + meta + '</div>') if meta else ''}
    <a href="{url}" target="_blank" rel="noopener" class="card-link">Bekijk woning \u2192</a>
  </div>
</div>"""

    if not listings:
        cards_html = """
<div class="empty">
  <div class="icon">\U0001f50d</div>
  <h2>Nog geen woningen gevonden</h2>
  <p>De bot zoekt elke 15 minuten. Pas je <a href="/instellingen">voorkeuren</a> aan als je niets verwacht.</p>
</div>"""

    # ── Paginering ──
    pager_html = ""
    if totaal_paginas > 1:
        items = []
        if page > 1:
            items.append(f'<a href="?page={page - 1}">\u2039</a>')
        for p in range(1, totaal_paginas + 1):
            if p == page:
                items.append(f'<span class="cur">{p}</span>')
            else:
                items.append(f'<a href="?page={p}">{p}</a>')
        if page < totaal_paginas:
            items.append(f'<a href="?page={page + 1}">\u203a</a>')
        pager_html = '<div class="pager">' + "".join(items) + "</div>"

    filter_info = f"{stad} \u00b7 \u20ac\u00a0{min_prijs}\u2013{max_prijs}/maand"
    if types:
        filter_info += " \u00b7 " + ", ".join(types)

    body = f"""
<div class="container">
  <div class="page-head">
    <h1>Beschikbare woningen</h1>
    <p>{totaal} woningen gevonden \u00b7 {filter_info}</p>
  </div>
  <div class="grid">{cards_html}</div>
  {pager_html}
</div>"""

    return _page("Woningen", body)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
