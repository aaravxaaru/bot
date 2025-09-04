# monitor_group.py
# Group Name (and optional image) locker/monitor — UI like your screenshot
# Requirements: pip install flask requests
# Use responsibly: provide only AppState cookies you own and operate on groups/chats you are allowed to control.

import os
import re
import json
import time
import urllib.parse
import threading
from threading import Event
from flask import Flask, request, render_template_string, redirect, url_for, flash, jsonify

import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# In-memory monitors keyed by group/thread id
monitors = {}  # group_id -> {"thread": Thread, "stop": Event, "session": Requests.Session, "target_name": str, "last_status": str}

# ====== UI Template (dark theme similar to your screenshot) ======
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>🔒 Group Name & Image Locker</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <style>
    body { background:#121212; color:#ddd; font-family:Inter,Arial,Helvetica,sans-serif; }
    .panel { max-width:1100px; margin:40px auto; background:#2b2b2b; border-radius:10px; padding:40px; box-shadow:0 10px 40px rgba(0,0,0,0.6); }
    h1 { color:#9fb0ff; font-weight:700; text-align:center; }
    textarea, input { background:#333; color:#ddd; border:1px solid #444; }
    .form-control:focus { box-shadow:none; border-color:#6f8cff; }
    .btn-primary { background:#6f8cff; border:none; }
    .small-note { color:#9aa; font-size:0.9rem; }
    .status-box { background:#111; color:#9df; padding:12px; border-radius:8px; margin-top:12px; font-family:monospace; white-space:pre-wrap; max-height:220px; overflow:auto; }
    label { color:#cfd8ff; }
  </style>
</head>
<body>
  <div class="panel">
    <h1>🔒 Group Name & Image Locker</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <script>
            Swal.fire({ icon: '{{ "error" if category=="error" else "success" }}', title: '{{ "Error" if category=="error" else "Success" }}', text: '{{ message }}' });
          </script>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post" action="/start" style="max-width:820px;margin:auto;">
      <div class="mb-3">
        <label>Paste appstate JSON here</label>
        <textarea name="appState" class="form-control" rows="6" placeholder='Paste AppState JSON array/object or cookie string like "c_user=...; xs=...;"' required>{{ request.form.appState or "" }}</textarea>
      </div>

      <div class="mb-3">
        <label>Group ID</label>
        <input name="groupId" class="form-control" placeholder="Group ID or thread id (e.g. 123456789012345 or t_123...)" value="{{ request.form.groupId or "" }}" required>
      </div>

      <div class="mb-3">
        <label>Enforced Group Name</label>
        <input name="enforcedName" class="form-control" placeholder="The name to enforce" value="{{ request.form.enforcedName or "" }}" required>
      </div>

      <div class="form-check mb-3">
        <input class="form-check-input" type="checkbox" id="imageProtect" name="imageProtect" {% if request.form.imageProtect %}checked{% endif %}>
        <label class="form-check-label small-note" for="imageProtect">Enable Group Image Protection (placeholder)</label>
      </div>

      <div class="d-flex justify-content-center">
        <button class="btn btn-primary px-4 py-2" type="submit">Start Monitoring</button>
      </div>
    </form>

    <div style="max-width:820px;margin:24px auto;">
      <h5 style="color:#cfe">Active Monitors</h5>
      {% if monitors %}
        {% for gid, info in monitors.items() %}
          <div style="background:#1e1e1e;padding:12px;margin-bottom:10px;border-radius:8px;">
            <strong>Group:</strong> {{ gid }} &nbsp; | &nbsp; <strong>Target:</strong> {{ info['target_name'] }} &nbsp; | &nbsp; <strong>Status:</strong> {{ info.get('last_status','starting') }}
            <div style="margin-top:8px;">
              <form method="post" action="/stop" style="display:inline-block;">
                <input type="hidden" name="groupId" value="{{ gid }}">
                <button class="btn btn-sm btn-danger">Stop</button>
              </form>
              <form method="get" action="/log" style="display:inline-block;margin-left:8px;">
                <input type="hidden" name="groupId" value="{{ gid }}">
                <button class="btn btn-sm btn-outline-light">View Log</button>
              </form>
            </div>
          </div>
        {% endfor %}
      {% else %}
        <p class="small-note">No monitors running.</p>
      {% endif %}

      <h5 style="color:#cfe;margin-top:18px;">Server Log (recent)</h5>
      <div class="status-box">{{ server_log }}</div>
    </div>

    <p class="small-note" style="text-align:center;margin-top:18px;">Use only your own credentials. This tool will attempt automatic POSTs to Facebook mobile endpoints to re-apply the name.</p>
  </div>
</body>
</html>
"""

# Simple rotating server-side log buffer
SERVER_LOG = []
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    SERVER_LOG.append(line)
    if len(SERVER_LOG) > 400:
        SERVER_LOG.pop(0)
    print(line)

# Helper: parse AppState into cookies (supports JSON list/dict or cookie string)
def parse_appstate_to_cookies(text):
    # try JSON
    try:
        data = json.loads(text)
        cookies = {}
        if isinstance(data, dict):
            if "cookies" in data and isinstance(data["cookies"], list):
                for c in data["cookies"]:
                    k = c.get("name") or c.get("key")
                    v = c.get("value") or c.get("val")
                    if k and v is not None:
                        cookies[k] = str(v)
            else:
                for k,v in data.items():
                    if isinstance(v,str):
                        cookies[k] = v
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    k = item.get("name") or item.get("key")
                    v = item.get("value") or item.get("val")
                    if k and v is not None:
                        cookies[k] = str(v)
        if cookies:
            return cookies
    except Exception as e:
        log(f"AppState JSON parse failed: {e}")

    # cookie string fallback
    parts = re.split(r";\s*", text.strip())
    cookies = {}
    for p in parts:
        if "=" in p:
            k,v = p.split("=",1)
            cookies[k.strip()] = v.strip()
    if cookies:
        return cookies

    raise ValueError("Could not parse AppState. Provide JSON or cookie-string.")

# Find candidate form in HTML and action URL (for rename)
def find_form_and_action(html, base_url):
    forms = re.finditer(r'(<form\b[^>]*>.*?</form>)', html, flags=re.DOTALL|re.IGNORECASE)
    for fm in forms:
        fh = fm.group(1)
        # heuristic: look for title/name inputs or fb_dtsg
        if re.search(r'name=["\'](?:title|thread_title|subject|thread_name|group_name|name)["\']', fh, flags=re.IGNORECASE) \
           or re.search(r'name=["\']fb_dtsg["\']', fh, flags=re.IGNORECASE):
            m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', fh, flags=re.IGNORECASE)
            action = urllib.parse.urljoin(base_url, m.group(1)) if m else base_url
            return fh, action
    return None, None

def extract_inputs_from_form(form_html):
    inputs={}
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*\bvalue=["\']([^"\']*)["\']', form_html, flags=re.IGNORECASE):
        inputs[m.group(1)] = m.group(2)
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*>', form_html, flags=re.IGNORECASE):
        if m.group(1) not in inputs:
            inputs[m.group(1)] = ""
    for m in re.finditer(r'<textarea\b[^>]*\bname=["\']([^"\']+)["\'][^>]*>(.*?)</textarea>', form_html, flags=re.IGNORECASE|re.DOTALL):
        inputs[m.group(1)] = m.group(2) or ""
    return inputs

# Attempt to submit rename on a page
def try_change_on_page(session, page_url, group_id, new_name):
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": page_url}
    try:
        r = session.get(page_url, headers=headers, timeout=14)
    except Exception as e:
        return False, f"GET {page_url} failed: {e}"
    if r.status_code >= 400:
        return False, f"GET {page_url} returned {r.status_code}"
    # find form
    form_html, action = find_form_and_action(r.text, page_url)
    if not form_html:
        return False, "No suitable form found on page"
    inputs = extract_inputs_from_form(form_html)
    # find name field
    candidates = ['group_name','group[name]','thread_title','title','name','subject','thread_name','display_name']
    name_field = next((c for c in candidates if c in inputs), None)
    if not name_field:
        m = re.search(r'<input[^>]+type=["\']text["\'][^>]*name=["\']([^"\']+)["\']', form_html, flags=re.IGNORECASE)
        if m:
            name_field = m.group(1)
    if not name_field:
        return False, "Could not detect name field in form"
    payload = {k:v for k,v in inputs.items()}
    payload[name_field] = new_name
    # tokens fallback
    fb = re.search(r'name=["\']fb_dtsg["\']\s+value=["\']([^"\']+)["\']', r.text, flags=re.IGNORECASE)
    if fb and 'fb_dtsg' not in payload:
        payload['fb_dtsg'] = fb.group(1)
    jz = re.search(r'name=["\']jazoest["\']\s+value=["\']([^"\']+)["\']', r.text, flags=re.IGNORECASE)
    if jz and 'jazoest' not in payload:
        payload['jazoest'] = jz.group(1)
    try:
        resp = session.post(action, data=payload, headers={**headers, "Content-Type":"application/x-www-form-urlencoded"}, timeout=15, allow_redirects=True)
    except Exception as e:
        return False, f"POST failed: {e}"
    # verify by fetching group/thread pages
    checks = [
        f"https://mbasic.facebook.com/groups/{group_id}",
        f"https://mbasic.facebook.com/messages/t/{group_id}",
        f"https://m.facebook.com/messages/t/{group_id}",
        f"https://www.messenger.com/t/{group_id}"
    ]
    for cu in checks:
        try:
            cr = session.get(cu, headers=headers, timeout=10)
            if cr.status_code==200 and new_name.lower() in cr.text.lower():
                return True, f"Verified on {cu}"
        except Exception:
            continue
    if new_name.lower() in resp.text.lower():
        return True, "Rename appears in response"
    return False, "Posted but could not verify new name on known pages (maybe permission/session issue)"

# Monitor thread function
def monitor_loop(group_id, session, new_name, stop_event, interval=5):
    log_path = os.path.join(LOG_DIR, f"monitor_{group_id}.log")
    monitors[group_id]['last_status'] = "running"
    log(f"Monitor started for {group_id} -> enforcing '{new_name}' every {interval}s")
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Monitor started -> enforce '{new_name}'\n")
    try:
        while not stop_event.is_set():
            # Try candidate pages in order
            candidates = [
                f"https://mbasic.facebook.com/groups/{group_id}/edit/",
                f"https://mbasic.facebook.com/groups/{group_id}",
                f"https://mbasic.facebook.com/messages/t/{group_id}",
                f"https://m.facebook.com/messages/t/{group_id}",
                f"https://www.messenger.com/t/{group_id}"
            ]
            success = False
            last_msg = None
            for p in candidates:
                ok,msg = try_change_on_page(session, p, group_id, new_name)
                last_msg = msg
                if ok:
                    success = True
                    break
                time.sleep(0.4)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] attempt -> success={success} msg={last_msg}\\n")
            monitors[group_id]['last_status'] = f"last: {last_msg}"
            log(f"Monitor {group_id}: attempt result -> {success} - {last_msg}")
            # sleep or stop
            if stop_event.wait(timeout=interval):
                break
    finally:
        monitors[group_id]['last_status'] = "stopped"
        log(f"Monitor for {group_id} stopped")

# Routes
@app.route("/", methods=["GET"])
def home():
    server_log = "\\n".join(SERVER_LOG[-120:])
    return render_template_string(INDEX_HTML, monitors=monitors, server_log=server_log)

@app.route("/start", methods=["POST"])
def start_monitor():
    appstate = request.form.get("appState","").strip()
    group_id = request.form.get("groupId","").strip()
    enforced = request.form.get("enforcedName","").strip()
    image_protect = request.form.get("imageProtect") == "on"
    if not appstate or not group_id or not enforced:
        flash("All fields are required", "error")
        return redirect(url_for("home"))
    # parse cookies
    try:
        cookies = parse_appstate_to_cookies(appstate)
    except Exception as e:
        flash(f"AppState parse error: {e}", "error")
        return redirect(url_for("home"))
    # create session
    session = requests.Session()
    for k,v in cookies.items():
        session.cookies.set(k, v)
    # quick check
    try:
        r = session.get("https://mbasic.facebook.com/", timeout=10)
    except Exception as e:
        flash(f"Network error contacting Facebook: {e}", "error")
        return redirect(url_for("home"))
    # prepare monitor structure
    if group_id in monitors and monitors[group_id].get("thread") and monitors[group_id]["thread"].is_alive():
        flash("A monitor for this group is already running", "error")
        return redirect(url_for("home"))
    stop_ev = Event()
    monitors[group_id] = {"thread": None, "stop": stop_ev, "session": session, "target_name": enforced, "last_status":"initializing"}
    t = threading.Thread(target=monitor_loop, args=(group_id, session, enforced, stop_ev, 6), daemon=True)
    monitors[group_id]["thread"] = t
    t.start()
    flash(f"Started monitoring {group_id} — enforcing '{enforced}'", "success")
    return redirect(url_for("home"))

@app.route("/stop", methods=["POST"])
def stop_monitor():
    group_id = request.form.get("groupId","").strip()
    rec = monitors.get(group_id)
    if not rec:
        flash("No such monitor running", "error")
        return redirect(url_for("home"))
    rec["stop"].set()
    flash(f"Stopping monitor for {group_id}", "success")
    return redirect(url_for("home"))

@app.route("/log")
def view_log():
    group_id = request.args.get("groupId","").strip()
    lf = os.path.join(LOG_DIR, f"monitor_{group_id}.log")
    if not os.path.exists(lf):
        return "No log yet for this group.", 200
    with open(lf, "r", encoding="utf-8") as f:
        return "<pre>" + f.read()[-20000:] + "</pre>", 200

@app.route("/status")
def status():
    return jsonify({gid: {"target":rec["target_name"], "status":rec.get("last_status","unknown")} for gid,rec in monitors.items()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=False recommended to avoid double-run/thread issues
    app.run(host="0.0.0.0", port=port, debug=False)
