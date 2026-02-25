from flask import Flask, request, render_template_string, redirect
import json, os

app = Flask(__name__)
CONFIG_FILE = '/app/data/config.json'

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        config = {
            'stad': request.form.get('stad', 'den-haag'),
            'radius': int(request.form.get('radius', 10)),
            'min_prijs': int(request.form.get('min_prijs', 0)),
            'max_prijs': int(request.form.get('max_prijs', 1200)),
            'telegram_username': request.form.get('telegram_username', ''),
        }
        os.makedirs('/app/data', exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return redirect('/?saved=1')

    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    saved = request.args.get('saved', 0)
    return render_template_string(HTML_TEMPLATE, config=config, saved=saved)

HTML_TEMPLATE = '''
<!DOCTYPE html><html><head><title>Huiszoeker</title>
<style>body{font-family:sans-serif;max-width:500px;margin:40px auto;padding:0 20px}
input{width:100%;padding:8px;margin:4px 0 12px;box-sizing:border-box}
button{background:#1F4E79;color:white;padding:10px 20px;border:none;cursor:pointer;border-radius:4px}</style>
</head><body>
<h1>🏠 Huiszoeker Instellingen</h1>
{% if saved %}<p style='color:green'>✅ Instellingen opgeslagen!</p>{% endif %}
<form method='POST'>
  <label>Stad:</label><input name='stad' value='{{ config.get("stad","den-haag") }}'>
  <label>Radius (km):</label><input type='number' name='radius' value='{{ config.get("radius",10) }}'>
  <label>Min prijs (€):</label><input type='number' name='min_prijs' value='{{ config.get("min_prijs",0) }}'>
  <label>Max prijs (€):</label><input type='number' name='max_prijs' value='{{ config.get("max_prijs",1200) }}'>
  <label>Telegram username:</label><input name='telegram_username' value='{{ config.get("telegram_username","") }}' placeholder='bijv. @jouwusername'>
  <button type='submit'>💾 Opslaan</button>
</form></body></html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
