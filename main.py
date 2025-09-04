# chat_rename.py
import os
import re
import json
import time
import urllib.parse
import requests
from flask import Flask, request, render_template_string, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chat Group Renamer by Aarav Shrivastava</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <style>
    body { background-color: #f8f9fa; color: #333; }
    .container { max-width: 600px; background: white; border-radius: 15px; padding: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); margin-top: 40px; }
    .form-control { border: 2px solid #dee2e6; border-radius: 8px; padding: 12px; margin-bottom: 15px; }
    .btn-primary { background: linear-gradient(45deg, #0d6efd, #6f42c1); border: none; padding: 12px 30px; border-radius: 8px; font-weight: 600; }
    .header { text-align: center; margin-bottom: 20px; }
    .header h2 { color: #0d6efd; font-weight: 700; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>✏️ Chat Group Renamer</h2>
      <p class="text-muted">Paste your AppState (cookies) and the thread ID (messenger thread). Use only your own account.</p>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <script>
            Swal.fire({
              icon: '{{ "error" if category == "error" else "success" }}',
              title: '{{ "Error" if category == "error" else "Success" }}',
              text: '{{ message }}'
            })
          </script>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post">
      <div class="mb-3">
        <label class="form-label">📱 AppState (JSON array/dict or cookie string)</label>
        <textarea name="appState" class="form-control" rows="5" placeholder='Paste AppState JSON (like [{"name":"c_user","value":"..."}]) or cookie string "c_user=...; xs=...;"' required></textarea>
      </div>

      <div class="mb-3">
        <label class="form-label">🆔 Thread ID (thread identifier)</label>
        <input type="text" name="threadId" class="form-control" placeholder="e.g. t_123456789012345 or 123456789012345" required>
      </div>

      <div class="mb-3">
        <label class="form-label">📝 New Chat Name</label>
        <input type="text" name="newName" class="form-control" placeholder="Enter new chat/group name" required>
      </div>

      <button type="submit" class="btn btn-primary w-100">🚀 Rename Chat</button>
    </form>

    <div style="margin-top:18px; color:#666; font-size:0.9rem;">
      <p>Use only for chats you are allowed to rename. I am not responsible for misuse.</p>
      <p>Developed by <strong>Aarav Shrivastava</strong></p>
    </div>
  </div>
</body>
</html>
"""

# ---------- Helpers ----------
def parse_appstate_to_cookies(app_state_text):
    """
    Accepts JSON array/dict (common AppState exporters) or cookie-string.
    Returns dict of cookies {name: value} or raises ValueError.
    """
    # try JSON
    try:
        data = json.loads(app_state_text)
        cookies = {}
        if isinstance(data, dict):
            # maybe {"cookies":[{"name":"c_user","value":"..."}]}
            if "cookies" in data and isinstance(data["cookies"], list):
                for c in data["cookies"]:
                    n = c.get("name") or c.get("key")
                    v = c.get("value")
                    if n and v is not None:
                        cookies[n] = str(v)
            else:
                # maybe name:value pairs
                for k, v in data.items():
                    if isinstance(v, str):
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
    except Exception:
        pass

    # try cookie string "k=v; k2=v2"
    parts = re.split(r";\s*", app_state_text.strip())
    cookies = {}
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                cookies[k] = v
    if cookies:
        return cookies

    raise ValueError("AppState parse failed. Provide JSON array/dict or cookie string.")

def find_form_and_action(html, base_url):
    """
    Return (form_html, action_url) for first form that likely has a thread title/name input.
    """
    forms = re.finditer(r'(<form\b[^>]*>.*?</form>)', html, flags=re.DOTALL | re.IGNORECASE)
    for fm in forms:
        fh = fm.group(1)
        # look for candidate name fields or fb_dtsg token
        if re.search(r'name=["\'](?:title|thread_title|subject|thread_name|name)["\']', fh, flags=re.IGNORECASE) \
           or re.search(r'name=["\']fb_dtsg["\']', fh, flags=re.IGNORECASE):
            m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', fh, flags=re.IGNORECASE)
            action = urllib.parse.urljoin(base_url, m.group(1)) if m else base_url
            return fh, action
    return None, None

def extract_inputs_from_form(form_html):
    inputs = {}
    # inputs with value
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*\bvalue=["\']([^"\']*)["\']', form_html, flags=re.IGNORECASE):
        inputs[m.group(1)] = m.group(2)
    # inputs without value attribute
    for m in re.finditer(r'<input\b[^>]*\bname=["\']([^"\']+)["\'][^>]*>', form_html, flags=re.IGNORECASE):
        if m.group(1) not in inputs:
            inputs[m.group(1)] = ""
    # also try textarea name
    for m in re.finditer(r'<textarea\b[^>]*\bname=["\']([^"\']+)["\'][^>]*>(.*?)</textarea>', form_html, flags=re.IGNORECASE|re.DOTALL):
        inputs[m.group(1)] = m.group(2) or ""
    return inputs

def try_rename_with_page(session, page_url, thread_id, new_name):
    """
    Try open page_url, find rename form and submit. Return (True,msg) on success, else (False,msg).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36",
        "Referer": page_url
    }
    try:
        r = session.get(page_url, headers=headers, timeout=15)
    except Exception as e:
        return False, f"GET {page_url} failed: {e}"

    if r.status_code >= 400:
        return False, f"GET {page_url} returned status {r.status_code}"

    # find form likely used to rename thread
    form_html, action = find_form_and_action(r.text, page_url)
    if not form_html:
        return False, "No suitable rename form found on this page."

    inputs = extract_inputs_from_form(form_html)

    # determine name field
    candidates = ['thread_title', 'title', 'subject', 'name', 'thread_name', 'chat_name']
    name_field = next((c for c in candidates if c in inputs), None)
    if not name_field:
        # try any text input
        m = re.search(r'<input[^>]+type=["\']text["\'][^>]*name=["\']([^"\']+)["\']', form_html, flags=re.IGNORECASE)
        if m:
            name_field = m.group(1)

    if not name_field:
        return False, "Could not detect name field in form."

    payload = {k: v for k, v in inputs.items()}
    payload[name_field] = new_name

    # fallback: also try fb_dtsg/jazoest extraction
    if 'fb_dtsg' not in payload:
        fb = re.search(r'name=["\']fb_dtsg["\']\s+value=["\']([^"\']+)["\']', r.text, flags=re.IGNORECASE)
        if fb:
            payload['fb_dtsg'] = fb.group(1)
    if 'jazoest' not in payload:
        jz = re.search(r'name=["\']jazoest["\']\s+value=["\']([^"\']+)["\']', r.text, flags=re.IGNORECASE)
        if jz:
            payload['jazoest'] = jz.group(1)

    try:
        resp = session.post(action, data=payload, headers={**headers, "Content-Type":"application/x-www-form-urlencoded"}, timeout=20, allow_redirects=True)
    except Exception as e:
        return False, f"POST to {action} failed: {e}"

    # verify: fetch thread page and look for new_name
    try:
        # try multiple URLs for thread display
        check_urls = [
            f"https://mbasic.facebook.com/messages/t/{thread_id}",
            f"https://m.facebook.com/messages/t/{thread_id}",
            f"https://www.messenger.com/t/{thread_id}"
        ]
        for cu in check_urls:
            try:
                cr = session.get(cu, headers=headers, timeout=12)
                if cr.status_code == 200 and new_name.lower() in cr.text.lower():
                    return True, f"Renamed successfully (verified on {cu})."
            except Exception:
                continue
        # also check response page text
        if new_name.lower() in resp.text.lower():
            return True, "Rename seems successful (found new name in response)."
        return False, "Rename POST completed but verification failed: new name not found."
    except Exception as e:
        return False, f"Verification failed: {e}"

def rename_chat_thread(app_state_text, thread_id, new_name):
    # parse cookies
    try:
        cookies = parse_appstate_to_cookies(app_state_text)
    except ValueError as e:
        return False, str(e)

    session = requests.Session()
    for k, v in cookies.items():
        session.cookies.set(k, v)

    # quick check login
    try:
        home = session.get("https://mbasic.facebook.com/", timeout=10)
        if home.status_code >= 400:
            return False, "Cannot contact mbasic.facebook.com for login check."
    except Exception as e:
        return False, f"Network error: {e}"

    # candidate pages to try rename form on (many variants)
    candidates = [
        f"https://mbasic.facebook.com/messages/t/{thread_id}",
        f"https://m.facebook.com/messages/t/{thread_id}",
        f"https://www.messenger.com/t/{thread_id}",
        f"https://mbasic.facebook.com/messages/read/?tid={thread_id}",
        f"https://mbasic.facebook.com/messages/read/?mid={thread_id}",
        f"https://mbasic.facebook.com/messages/?thread_id={thread_id}"
    ]

    last_msg = None
    for page in candidates:
        ok, msg = try_rename_with_page(session, page, thread_id, new_name)
        if ok:
            return True, msg
        last_msg = msg
        time.sleep(0.5)  # polite pause

    return False, f"All attempts failed. Last: {last_msg}"

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        app_state = request.form.get("appState", "").strip()
        thread_id = request.form.get("threadId", "").strip()
        new_name = request.form.get("newName", "").strip()

        if not app_state or not thread_id or not new_name:
            flash("All fields are required!", "error")
            return redirect(url_for("index"))

        success, message = rename_chat_thread(app_state, thread_id, new_name)
        if success:
            flash(message, "success")
        else:
            flash(message, "error")
        return redirect(url_for("index"))

    return render_template_string(INDEX_HTML)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # set debug=False in production
    app.run(host="0.0.0.0", port=port, debug=True)
