# final_namelock_fixed.py
import os
import time
import json
import datetime
import logging
from threading import Thread, Event
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, flash, send_file

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Tasks store + logs dir
tasks = {}
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Template (only changed safe dict access + added View Log / Stop buttons)
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
    .container { max-width: 700px; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 6px 24px rgba(0,0,0,0.08); margin: 30px auto; }
    .task-card { background: #f8f9fa; border-left: 4px solid #0d6efd; padding: 12px; margin: 10px 0; border-radius: 8px; }
    .task-actions { margin-top:10px; }
  </style>
</head>
<body>
  <div class="container">
    <h3>🔒 Group Name Changer</h3>
    <p class="text-muted">Tool by Aarav Shrivastava</p>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">📱 AppState (JSON)</label>
        <textarea name="appState" class="form-control" rows="4" placeholder='Paste your AppState JSON here...' required></textarea>
      </div>

      <div class="mb-3">
        <label class="form-label">🆔 Group UID</label>
        <input type="text" name="groupUid" class="form-control" placeholder="1234567890123456" required>
      </div>

      <div class="mb-3">
        <label class="form-label">📝 Group Name to Lock</label>
        <input type="text" name="groupName" class="form-control" placeholder="Enter the name to lock" required>
      </div>

      <button type="submit" class="btn btn-primary w-100 mb-3">🚀 Start Name Locking</button>
    </form>

    {% if active_tasks %}
      <h5>📋 Active Tasks</h5>
      {% for task_id, task_info in active_tasks.items() %}
        <div class="task-card">
          <strong>Task ID:</strong> {{ task_id }}<br>
          <strong>Group UID:</strong> {{ task_info['meta']['group_uid'] }}<br>
          <strong>Locked Name:</strong> {{ task_info['meta']['group_name'] }}<br>
          <strong>Status:</strong> <span class="badge bg-{{ 'success' if task_info['status'] == 'running' else 'danger' }}">{{ task_info['status'] }}</span><br>
          <strong>Created:</strong> {{ task_info['meta']['created_at'] }}<br>
          <div class="task-actions">
            <a class="btn btn-sm btn-outline-primary" href="/logs/{{ task_id }}" target="_blank">View Log</a>
            <button class="btn btn-sm btn-danger" onclick="stopTask('{{ task_id }}')">Stop</button>
          </div>
        </div>
      {% endfor %}
    {% else %}
      <p class="text-muted">No active tasks.</p>
    {% endif %}

    <div style="margin-top:18px; font-size:0.9rem; color:#666;">Developed by <strong>Aarav Shrivastava</strong></div>
  </div>

<script>
function stopTask(id){
  fetch('/stop/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(j => {
      if(j.ok){
        Swal.fire({ icon: 'success', title: 'Stopped', text: j.message }).then(()=> location.reload());
      } else {
        Swal.fire({ icon: 'error', title: 'Error', text: j.message });
      }
    })
    .catch(e=> Swal.fire({ icon:'error', title:'Network error' }));
}
</script>

{% if success %}
<script>
Swal.fire({ icon:'success', title:'Task Started', text:'Task ID: {{ task_id }}' }).then(()=> location.reload());
</script>
{% endif %}
</body>
</html>
"""

# Worker (unchanged simulation)
def name_lock_worker(task_id, app_state, group_uid, group_name, interval):
    app.logger.info(f"Worker started for {task_id}")
    meta = tasks.get(task_id)
    if not meta:
        app.logger.error("Task not found inside worker")
        return

    stop_event = meta["stop"]
    log_path = meta["log_file"]
    meta["status"] = "running"

    try:
        while not stop_event.is_set():
            try:
                entry = {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "task_id": task_id,
                    "group_uid": group_uid,
                    "target_name": group_name,
                    "action": "check",
                    "status": "ok",
                    "message": f"Maintained name lock for '{group_name}'"
                }
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(entry, ensure_ascii=False) + "\n")

                meta.setdefault("recent", []).append(entry)
                if len(meta["recent"]) > 100:
                    meta["recent"].pop(0)

            except Exception as e:
                app.logger.exception("Worker inner error")
                err = {"timestamp": datetime.datetime.utcnow().isoformat()+"Z", "error": str(e)}
                try:
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write(json.dumps(err, ensure_ascii=False) + "\n")
                except Exception:
                    app.logger.exception("Failed to write worker error to log")

            # wait with event (allows fast stop)
            if stop_event.wait(timeout=2):
                break

    finally:
        if task_id in tasks:
            tasks[task_id]['status'] = 'stopped'
        app.logger.info(f"Worker stopped for {task_id}")

# Routes
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        app_state_content = request.form.get("appState", "").strip()
        if not app_state_content:
            flash("AppState is required", "error")
            return redirect(url_for("index"))

        # Try parse JSON just to validate
        try:
            if app_state_content.startswith('{') or app_state_content.startswith('['):
                app_state = json.loads(app_state_content)
            else:
                flash("AppState must be valid JSON", "error")
                return redirect(url_for("index"))
        except Exception as e:
            app.logger.debug(f"AppState parse error: {e}")
            flash("Invalid AppState JSON", "error")
            return redirect(url_for("index"))

        group_uid = request.form.get("groupUid", "").strip()
        group_name = request.form.get("groupName", "").strip()
        if not group_uid or not group_name:
            flash("Group UID and Group Name are required", "error")
            return redirect(url_for("index"))

        # create task
        task_id = os.urandom(4).hex()
        log_file = os.path.join(LOG_DIR, f"namelock_{task_id}.log")
        stop_ev = Event()

        tasks[task_id] = {
            "thread": None,
            "stop": stop_ev,
            "status": "initializing",
            "meta": {
                "group_uid": group_uid,
                "group_name": group_name,
                "created_at": datetime.datetime.utcnow().isoformat() + "Z",
                # store only a small preview of app_state for debugging (avoid storing secrets full)
                "app_state_preview": (app_state_content[:300] + '...') if len(app_state_content) > 300 else app_state_content
            },
            "log_file": log_file,
            "recent": []
        }

        # start worker
        t = Thread(target=name_lock_worker, args=(task_id, app_state, group_uid, group_name, 2))
        t.daemon = True
        tasks[task_id]["thread"] = t
        t.start()

        # pass active tasks back too so UI updates immediately
        active_tasks = {k: v for k, v in tasks.items() if v.get("status", "unknown") != "stopped"}
        return render_template_string(INDEX_HTML, success=True, task_id=task_id, active_tasks=active_tasks)

    # GET
    active_tasks = {k: v for k, v in tasks.items() if v.get("status", "unknown") != "stopped"}
    return render_template_string(INDEX_HTML, active_tasks=active_tasks)

@app.route("/stop/<task_id>", methods=["POST"])
def stop_task(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return jsonify({"ok": False, "message": "Task not found"}), 404
    rec["stop"].set()
    rec["status"] = "stopping"
    return jsonify({"ok": True, "message": f"Stopping task {task_id}"}), 200

@app.route("/logs/<task_id>")
def view_logs(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return "Task not found", 404
    lf = rec.get("log_file")
    if not os.path.exists(lf):
        return "No logs yet", 200
    # Return last 500 lines for preview
    with open(lf, "r", encoding="utf-8") as f:
        lines = f.readlines()[-500:]
    return "<pre>" + "".join(lines) + "</pre>", 200

@app.route("/download/<task_id>")
def download_log(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return "Task not found", 404
    lf = rec.get("log_file")
    if not os.path.exists(lf):
        return "No logs yet", 200
    return send_file(lf, as_attachment=True, download_name=os.path.basename(lf))

@app.route("/status/<task_id>")
def task_status(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({
        "task_id": task_id,
        "status": rec.get("status", "unknown"),
        "meta": rec.get("meta", {}),
        "recent_count": len(rec.get("recent", []))
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=False to avoid double-run and thread issues
    app.run(host="0.0.0.0", port=port, debug=False)
