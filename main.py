# chat_rename_debug.py
# Very-verbose debug helper to attempt messenger/chat rename via AppState cookies.
# For testing only. Use only with your own account/thread.
# pip install flask requests

import os, re, json, time, urllib.parse, logging
from flask import Flask, request, render_template_string, redirect, url_for, flash
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat-rename-debug")

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# small rotating server log buffer for UI
SERVER_LOG = []
def slog(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    SERVER_LOG.append(line)
    if len(SERVER_LOG) > 500:
        SERVER_LOG.pop(0)
    print(line)

INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Chat Rename Debug</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <style>
    body{background:#111;color:#ddd;font-family:Inter,Arial;padding:18px}
    .box{max-width:900px;margin:18px auto;background:#1f1f1f;padding:20px;border-radius:10px}
    textarea,input{background:#222;color:#ddd;border:1px solid #333}
    pre{background:#000;color:#bfb;padding:10px;border-radius:6px;overflow:auto;max-height:280px}
  </style>
</head>
<body>
<div class="box">
  <h3>Chat Rename — Debug (Very Verbose)</h3>
  <p class="text-muted">Paste AppState (JSON-array/dict or cookie string), thread id and desired name. Use only your account.</p>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat,msg in messages %}
        <script>Swal.fire({icon: '{{ "error" if cat=="error" else "success" }}', title: '{{ "Error" if cat=="error" else "Success" }}', text: `{{ msg }}`});</script>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <form method="post" action="/attempt">
    <div class="mb-3">
      <label>AppState (JSON array/dict OR cookie string)</label>
      <textarea name="appState" class="form-control" rows="6" required>{{ request.form.appState or "" }}</textarea>
    </div>
    <div class="row">
      <div class="col mb-3">
        <label>Thread ID</label>
        <input name="threadId" class="form-control" value="{{ request.form.threadId or "" }}" required>
      </div>
      <div class="col mb-3">
        <label>New Name</label>
        <input name="newName" class="form-control" value="{{ request.form.newName or "" }}" required>
      </div>
    </div>
    <button class="btn btn-primary">Attempt Rename</button>
  </form>

  <h5 class="mt-4">Server Log (latest)</h5>
  <pre>{{ server_log }}</pre>

  <p class="text-muted small">If it fails, copy the SweetAlert text AND the last ~40 lines of this server log and paste here so I can fix it quickly.</p>
</div>
</body>
</html>
"""

# ---------- Helpers ----------
def parse_appstate_to_cookies(app_state_text):
    # try JSON
    try:
        data = json.loads(app_state_text)
        cookies = {}
        if isinstance(data, dict):
            # common exporters: {"cookies":[{...}]}
            if "cookies" in data and isinstance(data["cookies"], list):
                for c in data["cookies"]:
                    n = c.get("name") or c.get("key")
                    v = c.get("value") or c.get("val")
                    if n and v is not None:
                        cookies[n] = str(v)
            else:
                # maybe simple dict
                for k,v in data.items():
                    if isinstance(v,str):
                        cookies[k] = v
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    n = item.get("name") or item.get("key")
                    v = item.get("value") or item.get("val")
                    if n and v is not None:
                        cookies[n] = str(v)
        if cookies:
            return cookies
    except Exception as e:
        slog(f"AppState JSON parse failed: {e}")

    # cookie-string fallback
    parts = re.split(r";\s*", app_state_text.strip())
    cookies = {}
    for p in parts:
        if "=" in p:
            k,v = p.split("=",1)
            cookies[k.strip()] = v.strip()
    if cookies:
        return cookies
    raise ValueError("Could not parse AppState. Provide JSON array/dict or cookie string.")

def extract_tokens_from_html(html):
    fb = re.search(r'name=["\']fb_dtsg["\']\s+value=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    jz = re.search(r'name=["\']jazoest["\']\s+value=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    return (fb.group(1) if fb else None, jz.group(1) if jz else None)

def find_form_and_action(html, base_url, heuristics=None):
    forms = re.finditer(r'(<form\b[^>]*>.*?</form>)', html, flags=re.DOTALL|re.IGNORECASE)
    for fm in forms:
        fh = fm.group(1)
        # if heuristics provided, require match
        if heuristics:
            if not any(re.search(h, fh, flags=re.IGNORECASE) for h in heuristics):
                continue
        m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', fh, flags=re.IGNORECASE)
        action = urllib.parse.urljoin(base_url, m.group(1)) if m else base_url
        return fh, action
    return None, None

def try_rename_once(session, url, thread_id, new_name):
    headers = {"User-Agent":"Mozilla/5.0", "Referer": url}
    slog(f"GET {url}")
    try:
        r = session.get(url, headers=headers, timeout=12)
    except Exception as e:
        return False, f"GET {url} failed: {e}", None
    slog(f"Status {r.status_code} length={len(r.text)}")
    fb_dtsg, jazoest = extract_tokens_from_html(r.text)
    slog(f"Extracted tokens fb_dtsg={'yes' if fb_dtsg else 'no'} jazoest={'yes' if jazoest else 'no'}")
    # find a form likely to contain rename field
    heuristics = [r'name=["\'](?:title|thread_title|subject|thread_name|name|group_name)["\']', r'fb_dtsg']
    fh, action = find_form_and_action(r.text, url, heuristics=heuristics)
    if not fh:
        # fallback: any form
        fh, action = find_form_and_action(r.text, url, heuristics=None)
    if not fh:
        return False, "No form found on page", r.text[:2000]
    slog(f"Found form action={action}")
    # extract inputs
    inputs = {}
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*\bvalue=["\']([^"\']*)["\']', fh, flags=re.IGNORECASE):
        inputs[m.group(1)] = m.group(2)
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*>', fh, flags=re.IGNORECASE):
        if m.group(1) not in inputs:
            inputs[m.group(1)] = ""
    # find likely name field
    name_candidates = ['thread_title','title','subject','thread_name','name','group_name','display_name']
    name_field = next((c for c in name_candidates if c in inputs), None)
    if not name_field:
        m = re.search(r'<input[^>]+type=["\']text["\'][^>]*name=["\']([^"\']+)["\']', fh, flags=re.IGNORECASE)
        name_field = m.group(1) if m else None
    if not name_field:
        return False, "Could not detect name field in form", fh[:2000]
    slog(f"Using name field: {name_field}")
    payload = {k:v for k,v in inputs.items()}
    payload[name_field] = new_name
    if 'fb_dtsg' not in payload and fb_dtsg:
        payload['fb_dtsg'] = fb_dtsg
    if 'jazoest' not in payload and jazoest:
        payload['jazoest'] = jazoest
    slog(f"Posting to {action} payload keys: {list(payload.keys())[:12]}")
    try:
        resp = session.post(action, data=payload, headers={**headers, "Content-Type":"application/x-www-form-urlencoded"}, timeout=15, allow_redirects=True)
    except Exception as e:
        return False, f"POST failed: {e}", None
    slog(f"POST status {resp.status_code} len={len(resp.text)}")
    # verify by checking common display pages
    checks = [
        f"https://mbasic.facebook.com/messages/t/{thread_id}",
        f"https://m.facebook.com/messages/t/{thread_id}",
        f"https://www.messenger.com/t/{thread_id}"
    ]
    for cu in checks:
        try:
            cr = session.get(cu, headers=headers, timeout=10)
            slog(f"Verify GET {cu} status {cr.status_code} len={len(cr.text)}")
            if new_name.lower() in cr.text.lower():
                return True, f"Verified on {cu}", cr.text[:2000]
        except Exception as e:
            slog(f"Verify GET {cu} failed: {e}")
            continue
    # if not found in checks, try to detect success message in resp
    if new_name.lower() in resp.text.lower():
        return True, "Found new name in response body", resp.text[:2000]
    return False, "POST done but new name not found (permission/session issue)", resp.text[:2000]

def rename_chat_verbose(app_state_text, thread_id, new_name):
    try:
        cookies = parse_appstate_to_cookies(app_state_text)
    except Exception as e:
        return False, f"AppState parse error: {e}", None
    session = requests.Session()
    for k,v in cookies.items():
        session.cookies.set(k, v)
    slog("Cookies loaded: " + ", ".join(list(cookies.keys())[:10]))
    # quick home get
    try:
        rh = session.get("https://mbasic.facebook.com/", timeout=10)
        slog(f"Home GET status {rh.status_code}")
    except Exception as e:
        return False, f"Network/home GET failed: {e}", None
    # candidate pages
    candidates = [
        f"https://mbasic.facebook.com/messages/t/{thread_id}",
        f"https://m.facebook.com/messages/t/{thread_id}",
        f"https://www.messenger.com/t/{thread_id}",
        f"https://mbasic.facebook.com/messages/read/?tid={thread_id}",
    ]
    last_msg = None
    last_snip = None
    for p in candidates:
        ok,msg,sn = try_rename_once(session, p, thread_id, new_name)
        last_msg = msg
        last_snip = sn
        if ok:
            return True, msg, sn
        time.sleep(0.4)
    return False, f"All attempts failed. Last: {last_msg}", last_snip

# Routes
@app.route("/", methods=["GET"])
def home():
    return render_template_string(INDEX_HTML, server_log="\n".join(SERVER_LOG[-200:]))

@app.route("/attempt", methods=["POST"])
def attempt():
    app_state = request.form.get("appState","").strip()
    thread_id = request.form.get("threadId","").strip()
    new_name = request.form.get("newName","").strip()
    if not app_state or not thread_id or not new_name:
        flash("All fields are required", "error")
        return redirect(url_for("home"))
    slog("=== Starting rename attempt ===")
    ok,msg,sn = rename_chat_verbose(app_state, thread_id, new_name)
    if ok:
        flash(msg, "success")
    else:
        # include short snippet in message (sanitized)
        short = (sn[:600] + "...") if isinstance(sn,str) and sn else ""
        flash(f"{msg} | snippet: {short}", "error")
    slog("=== Attempt finished ===")
    return redirect(url_for("home"))

if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=True)
