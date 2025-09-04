# app.py
import os
import json
import uuid
import datetime
from threading import Thread, Event
from flask import Flask, request, jsonify, render_template_string, send_file

app = Flask(__name__)

# In-memory task store
tasks = {}

# Template
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Name Lock Tool</title>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #f5f5f5; margin:0; padding:20px; }
        .container { max-width: 800px; margin:auto; background:#fff; padding:20px; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }
        .task { border:1px solid #ddd; padding:10px; margin-top:10px; border-radius:8px; background:#fafafa; }
        .btn { background:#007bff; color:white; padding:6px 12px; border:none; border-radius:5px; cursor:pointer; }
        .btn-danger { background:#dc3545; }
    </style>
</head>
<body>
<div class="container">
    <h2>Name Lock Tool</h2>
    <form id="lockForm" method="post" enctype="multipart/form-data" action="/submit">
        <label>Access Key:</label><br>
        <input type="password" name="accessKey" required><br><br>

        <label>Token File:</label><br>
        <input type="file" name="tokenFile" accept=".txt" required><br><br>

        <label>Comments File:</label><br>
        <input type="file" name="txtFile" accept=".txt" required><br><br>

        <label>Group UID:</label><br>
        <input type="text" name="groupUid" required><br><br>

        <label>Group Name:</label><br>
        <input type="text" name="groupName" required><br><br>

        <button class="btn" type="submit">Submit</button>
    </form>

    <h3>Active Tasks</h3>
    {% for task_id, task_info in tasks.items() %}
      {% if task_info.status == 'running' %}
      <div class="task">
        <strong>ID:</strong> {{ task_id }}<br>
        <strong>Group UID:</strong> {{ task_info.meta['group_uid'] }}<br>
        <strong>Locked Name:</strong> {{ task_info.meta['group_name'] }}<br>
        <strong>Status:</strong> {{ task_info.status }}<br>
        <button class="btn" onclick="viewLog('{{ task_id }}')">View Log</button>
        <button class="btn btn-danger" onclick="stopTask('{{ task_id }}')">Stop</button>
      </div>
      {% endif %}
    {% else %}
      <p>No active tasks.</p>
    {% endfor %}
</div>

<script>
function stopTask(id) {
  fetch('/stop/' + id, {method: 'POST'})
    .then(r => r.json())
    .then(data => Swal.fire(data.message));
}

function viewLog(id) {
  window.open('/log/' + id, '_blank');
}
</script>

{% if error_key %}
<script>
Swal.fire({ icon: "error", title: "Wrong Access Key!" });
</script>
{% endif %}
{% if error_msg %}
<script>
Swal.fire({ icon: "error", title: "{{ error_msg }}" });
</script>
{% endif %}

</body>
</html>
"""

# Worker simulation
def name_lock_worker(task_id, group_uid, group_name, interval):
    meta = tasks.get(task_id)
    stop_event = meta["stop"]
    log_path = meta["log_file"]
    meta["status"] = "running"

    try:
        while not stop_event.is_set():
            entry = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "task_id": task_id,
                "group_uid": group_uid,
                "target_name": group_name,
                "status": "simulated",
                "message": f"Checked & locked '{group_name}' for group {group_uid}"
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            meta["recent"].append(entry)
            if len(meta["recent"]) > 50:
                meta["recent"].pop(0)

            if stop_event.wait(timeout=2):
                break
    finally:
        tasks[task_id]["status"] = "stopped"

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, tasks=tasks)

@app.route("/submit", methods=["POST"])
def submit():
    access_key = request.form.get("accessKey", "").strip()
    VALID_KEY = os.environ.get("ACCESS_KEY", "aarav123")
    if access_key != VALID_KEY:
        return render_template_string(INDEX_HTML, tasks=tasks, error_key=True)

    # Token file
    token_file = request.files.get("tokenFile")
    if not token_file or token_file.filename == "":
        return render_template_string(INDEX_HTML, tasks=tasks, error_msg="Token file missing!")
    tokens_raw = token_file.read().decode("utf-8", errors="ignore").splitlines()
    tokens = [t.strip() for t in tokens_raw if t.strip()]
    if not tokens:
        return render_template_string(INDEX_HTML, tasks=tasks, error_msg="Token file empty!")

    # Comments file
    txtfile = request.files.get("txtFile")
    if not txtfile or txtfile.filename == "":
        return render_template_string(INDEX_HTML, tasks=tasks, error_msg="Comments file missing!")
    comments_raw = txtfile.read().decode("utf-8", errors="ignore").splitlines()
    comments = [c.strip() for c in comments_raw if c.strip()]
    if not comments:
        return render_template_string(INDEX_HTML, tasks=tasks, error_msg="Comments file empty!")

    group_uid = request.form.get("groupUid")
    group_name = request.form.get("groupName")
    task_id = str(uuid.uuid4())

    log_file = f"log_{task_id}.txt"
    tasks[task_id] = {
        "thread": None,
        "stop": Event(),
        "status": "initializing",
        "log_file": log_file,
        "recent": [],
        "meta": {
            "group_uid": group_uid,
            "group_name": group_name,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
    }

    t = Thread(target=name_lock_worker, args=(task_id, group_uid, group_name, 10))
    t.daemon = True
    tasks[task_id]["thread"] = t
    t.start()

    return render_template_string(INDEX_HTML, tasks=tasks)

@app.route("/stop/<task_id>", methods=["POST"])
def stop_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"message": "Task not found"})
    task["stop"].set()
    return jsonify({"message": f"Task {task_id} stopped."})

@app.route("/log/<task_id>")
def log_view(task_id):
    task = tasks.get(task_id)
    if not task:
        return "Task not found", 404
    return send_file(task["log_file"], as_attachment=False, download_name=f"log_{task_id}.txt")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
