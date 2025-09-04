import os
import json
import time
import requests
from flask import Flask, request, render_template_string, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# ===================== HTML =====================
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Group Name Changer by Aarav Shrivastava</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <style>
    body { background-color: #f8f9fa; color: #333; }
    .container { max-width: 500px; background: white; border-radius: 15px; padding: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); margin-top: 50px; }
    .form-control { border: 2px solid #dee2e6; border-radius: 8px; padding: 12px; margin-bottom: 15px; }
    .form-control:focus { border-color: #0d6efd; box-shadow: 0 0 0 0.2rem rgba(13,110,253,.25); }
    .btn-primary { background: linear-gradient(45deg, #0d6efd, #6f42c1); border: none; padding: 12px 30px; border-radius: 8px; font-weight: 600; }
    .header { text-align: center; margin-bottom: 30px; }
    .header h2 { color: #0d6efd; font-weight: 700; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>🔒 Group Name Changer</h2>
      <p class="text-muted">Tool by Aarav Shrivastava</p>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <script>
            Swal.fire({
              icon: '{{ 'error' if category == 'error' else 'success' }}',
              title: '{{ 'Error' if category == 'error' else 'Success' }}',
              text: '{{ message }}'
            })
          </script>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post">
      <div class="mb-3">
        <label class="form-label">📱 AppState</label>
        <textarea name="appState" class="form-control" rows="4" placeholder="Paste your AppState JSON here..." required></textarea>
      </div>

      <div class="mb-3">
        <label class="form-label">🆔 Group UID</label>
        <input type="text" name="groupUid" class="form-control" placeholder="1234567890123456" required>
      </div>

      <div class="mb-3">
        <label class="form-label">📝 New Group Name</label>
        <input type="text" name="groupName" class="form-control" placeholder="Enter the new name" required>
      </div>

      <button type="submit" class="btn btn-primary w-100 mb-3">🚀 Change Group Name</button>
    </form>

    <div class="mt-4 text-center" style="border-top: 1px solid #dee2e6; padding-top: 20px; color: #6c757d; font-size: 0.9rem;">
      <p>All Rights Reserved<br>Developed by <strong>Aarav Shrivastava</strong></p>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ===================== FUNCTION =====================
def change_group_name(app_state, group_id, new_name):
    """Change FB group name using AppState cookies"""
    try:
        cookies = {c["key"]: c["value"] for c in json.loads(app_state)}
    except Exception:
        return False, "Invalid AppState format!"

    session = requests.Session()
    for k, v in cookies.items():
        session.cookies.set(k, v)

    # Step 1: Open group settings page
    settings_url = f"https://mbasic.facebook.com/groups/{group_id}/edit/?name"
    r = session.get(settings_url)
    if "mbasic_logout_button" not in r.text:
        return False, "Login failed! Invalid AppState or expired session."

    # Step 2: Extract fb_dtsg & jazoest hidden inputs
    import re
    fb_dtsg = re.search(r'name="fb_dtsg" value="(.*?)"', r.text)
    jazoest = re.search(r'name="jazoest" value="(.*?)"', r.text)
    if not fb_dtsg or not jazoest:
        return False, "Failed to get fb_dtsg token!"

    fb_dtsg = fb_dtsg.group(1)
    jazoest = jazoest.group(1)

    # Step 3: Submit form to change name
    post_url = f"https://mbasic.facebook.com/groups/edit/name/?group_id={group_id}"
    payload = {
        "fb_dtsg": fb_dtsg,
        "jazoest": jazoest,
        "group_name": new_name,
        "save": "Save"
    }
    resp = session.post(post_url, data=payload)

    if "The name of your group has been updated" in resp.text or new_name in resp.text:
        return True, f"Group name changed successfully to '{new_name}'!"
    else:
        return False, "Failed to change group name. Maybe not admin?"

# ===================== ROUTES =====================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        app_state = request.form.get("appState", "").strip()
        group_uid = request.form.get("groupUid", "").strip()
        group_name = request.form.get("groupName", "").strip()

        if not app_state or not group_uid or not group_name:
            flash("All fields are required!", "error")
            return redirect(url_for("index"))

        success, msg = change_group_name(app_state, group_uid, group_name)
        if success:
            flash(msg, "success")
        else:
            flash(msg, "error")

        return redirect(url_for("index"))

    return render_template_string(INDEX_HTML)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
