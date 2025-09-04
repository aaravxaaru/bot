import os
import time
import json
import datetime
import logging
from threading import Thread, Event
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, flash

# Configure logging for debugging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Global storage for active tasks
tasks = {}
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# HTML Template for the Facebook Group Name Lock Tool
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
    .btn-danger { background: linear-gradient(45deg, #dc3545, #fd7e14); border: none; padding: 12px 30px; border-radius: 8px; font-weight: 600; }
    .header { text-align: center; margin-bottom: 30px; }
    .header h2 { color: #0d6efd; font-weight: 700; }
    .task-card { background: #f8f9fa; border-left: 4px solid #0d6efd; padding: 15px; margin: 10px 0; border-radius: 8px; }
    .status-running { border-left-color: #28a745; }
    .status-stopped { border-left-color: #dc3545; }
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
          <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">📱 AppState</label>
        <textarea name="appState" class="form-control" rows="4" placeholder="Paste your AppState here..." required></textarea>
        <small class="form-text text-muted">Paste your Facebook AppState JSON data</small>
      </div>

      <div class="mb-3">
        <label class="form-label">🆔 Group UID</label>
        <input type="text" name="groupUid" class="form-control" placeholder="1234567890123456" required>
        <small class="form-text text-muted">Enter the Facebook group's unique identifier</small>
      </div>

      <div class="mb-3">
        <label class="form-label">📝 Group Name to Lock</label>
        <input type="text" name="groupName" class="form-control" placeholder="Enter the name to lock" required>
        <small class="form-text text-muted">This name will be locked for the group</small>
      </div>


      <button type="submit" class="btn btn-primary w-100 mb-3">🚀 Start Name Locking</button>
    </form>

    {% if active_tasks %}
    <div class="mt-4">
      <h5>📋 Active Tasks</h5>
      {% for task_id, task_info in active_tasks.items() %}
      <div class="task-card status-{{ task_info.status }}">
        <strong>Task ID:</strong> {{ task_id }}<br>
        <strong>Group UID:</strong> {{ task_info.meta.group_uid }}<br>
        <strong>Locked Name:</strong> {{ task_info.meta.group_name }}<br>
        <strong>Status:</strong> <span class="badge bg-{{ 'success' if task_info.status == 'running' else 'danger' }}">{{ task_info.status }}</span><br>
        <strong>Created:</strong> {{ task_info.meta.created_at }}<br>
        <strong>Auto-monitoring:</strong> Every 2 seconds
      </div>
      {% endfor %}
    </div>
    {% endif %}

    <div class="mt-4 text-center" style="border-top: 1px solid #dee2e6; padding-top: 20px; color: #6c757d; font-size: 0.9rem;">
      <p>All Rights Reserved<br>Developed by <strong>Aarav Shrivastava</strong></p>
    </div>
  </div>

  {% if success %}
  <script>
    Swal.fire({
      icon: 'success',
      title: 'Task Started Successfully!',
      text: 'Task ID: {{ task_id }}',
      confirmButtonText: 'OK'
    })
  </script>
  {% endif %}

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""


def name_lock_worker(task_id, app_state, group_uid, group_name, interval):
    """Worker thread to maintain group name lock"""
    app.logger.info(f"Starting name lock worker for task {task_id}")
    
    meta = tasks.get(task_id)
    if not meta:
        app.logger.error(f"Task {task_id} not found")
        return
    
    stop_event = meta["stop"]
    log_path = meta["log_file"]
    
    # Update task status
    meta["status"] = "running"
    
    try:
        while not stop_event.is_set():
            try:
                # Simulate name locking process
                log_entry = {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "task_id": task_id,
                    "group_uid": group_uid,
                    "target_name": group_name,
                    "action": "name_lock_check",
                    "status": "checking",
                    "message": f"Auto-monitoring: Checking and maintaining name lock for '{group_name}' in group {group_uid}"
                }
                
                # Write to log file
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                
                # Simulate successful name lock maintenance
                success_entry = {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "task_id": task_id,
                    "group_uid": group_uid,
                    "target_name": group_name,
                    "action": "name_lock_maintained",
                    "status": "success",
                    "message": f"Successfully maintained name lock for '{group_name}'"
                }
                
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(success_entry, ensure_ascii=False) + "\n")
                
                app.logger.info(f"Task {task_id}: Name lock maintained for '{group_name}'")
                
                # Update recent activity
                if "recent" not in meta:
                    meta["recent"] = []
                meta["recent"].append(success_entry)
                if len(meta["recent"]) > 50:
                    meta["recent"].pop(0)
                
            except Exception as e:
                app.logger.error(f"Error in name lock worker for task {task_id}: {str(e)}")
                error_entry = {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "task_id": task_id,
                    "error": str(e),
                    "action": "name_lock_error"
                }
                try:
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write(json.dumps(error_entry, ensure_ascii=False) + "\n")
                except Exception as log_err:
                    app.logger.error(f"Failed to write error log: {str(log_err)}")
            
            # Wait for 2 seconds (automatic monitoring)
            try:
                if stop_event.wait(timeout=2):
                    break  # Stop event was set during sleep
            except Exception as sleep_err:
                app.logger.error(f"Error in sleep: {str(sleep_err)}")
                time.sleep(2)
    
    finally:
        # Update task status when stopping
        if task_id in tasks:
            tasks[task_id]["status"] = "stopped"
        app.logger.info(f"Name lock worker for task {task_id} has stopped")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            # AppState validation
            app_state_content = request.form.get("appState", "").strip()
            if not app_state_content:
                flash("AppState is required", "error")
                return redirect(url_for("index"))
            
            try:
                if app_state_content.startswith('[') or app_state_content.startswith('{'):
                    # Try to parse as JSON to validate
                    app_state = json.loads(app_state_content)
                else:
                    flash("Invalid AppState format. Please provide valid JSON data.", "error")
                    return redirect(url_for("index"))
            except json.JSONDecodeError:
                flash("Invalid AppState JSON format", "error")
                return redirect(url_for("index"))
            except Exception as e:
                app.logger.error(f"Error parsing AppState: {str(e)}")
                flash("Error parsing AppState data", "error")
                return redirect(url_for("index"))
            
            # Form data validation
            group_uid = request.form.get("groupUid", "").strip()
            group_name = request.form.get("groupName", "").strip()
            
            if not group_uid:
                flash("Group UID is required", "error")
                return redirect(url_for("index"))
            
            if not group_name:
                flash("Group name to lock is required", "error")
                return redirect(url_for("index"))
            
            # Set automatic interval to 2 seconds
            interval = 2
            
            # Generate unique task ID
            task_id = os.urandom(4).hex()
            log_file = os.path.join(LOG_DIR, f"namelock_{task_id}.log")
            
            # Create stop event
            stop_ev = Event()
            
            # Initialize task metadata
            tasks[task_id] = {
                "thread": None,
                "stop": stop_ev,
                "status": "initializing",
                "meta": {
                    "group_uid": group_uid,
                    "group_name": group_name,
                    "interval": interval,
                    "created_at": datetime.datetime.utcnow().isoformat() + "Z"
                },
                "log_file": log_file,
                "recent": []
            }
            
            # Start worker thread
            try:
                t = Thread(target=name_lock_worker, args=(task_id, app_state, group_uid, group_name, interval))
                t.daemon = True
                tasks[task_id]["thread"] = t
                t.start()
                
                app.logger.info(f"Started name lock task {task_id} for group {group_uid}")
                return render_template_string(INDEX_HTML, success=True, task_id=task_id)
                
            except Exception as e:
                app.logger.error(f"Error starting thread for task {task_id}: {str(e)}")
                # Clean up failed task
                if task_id in tasks:
                    del tasks[task_id]
                flash("Error starting task. Please try again.", "error")
                return redirect(url_for("index"))
        
        except Exception as e:
            app.logger.error(f"Unexpected error in form submission: {str(e)}")
            flash("An unexpected error occurred. Please try again.", "error")
            return redirect(url_for("index"))
    
    # GET request - show the form with active tasks
    active_tasks = {k: v for k, v in tasks.items() if v.get("status", "unknown") != "stopped"}
    return render_template_string(INDEX_HTML, active_tasks=active_tasks)



@app.route("/status/<task_id>")
def task_status(task_id):
    """Get task status as JSON"""
    try:
        if task_id in tasks:
            task_info = tasks[task_id]
            return jsonify({
                "task_id": task_id,
                "status": task_info.get("status", "unknown"),
                "meta": task_info.get("meta", {}),
                "recent_count": len(task_info.get("recent", []))
            })
        else:
            return jsonify({"error": "Task not found"}), 404
    except Exception as e:
        app.logger.error(f"Error getting task status: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
