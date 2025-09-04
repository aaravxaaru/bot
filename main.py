from flask import Flask, request, jsonify
import json
from fbchat import Client
from fbchat.models import ThreadType

app = Flask(__name__)

# ------------------- HTML FRONTEND -------------------
html_page = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Group Name & Image Locker</title>
  <style>
    body {
      background-color: #1e1e1e;
      color: #fff;
      font-family: Arial, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
      margin: 0;
    }
    .container {
      background: #2c2c2c;
      padding: 30px;
      border-radius: 10px;
      width: 400px;
      text-align: center;
      box-shadow: 0 0 15px rgba(0,0,0,0.5);
    }
    textarea, input {
      width: 100%;
      padding: 10px;
      margin: 8px 0;
      border: none;
      border-radius: 5px;
      background: #3a3a3a;
      color: #fff;
    }
    button {
      background: #5a7dff;
      border: none;
      padding: 12px;
      width: 100%;
      color: white;
      border-radius: 5px;
      font-size: 16px;
      cursor: pointer;
    }
    button:hover {
      background: #4866d1;
    }
  </style>
</head>
<body>
  <div class="container">
    <h2>🔒 Group Name & Image Locker</h2>
    <form id="groupForm">
      <textarea name="appstate" placeholder="Paste appstate JSON here" required></textarea>
      <input type="text" name="group_id" placeholder="Group ID" required>
      <input type="text" name="new_name" placeholder="Enforced Group Name" required>
      <button type="submit">Start Monitoring</button>
    </form>
    <p id="result"></p>
  </div>

  <script>
    const form = document.getElementById("groupForm");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const formData = new FormData(form);
      const res = await fetch("/change_name", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      document.getElementById("result").innerText = data.message;
    });
  </script>
</body>
</html>
"""

# ------------------- ROUTES -------------------
@app.route("/")
def home():
    return html_page

@app.route("/change_name", methods=["POST"])
def change_name():
    try:
        # Get form data
        appstate_raw = request.form.get("appstate")
        group_id = request.form.get("group_id")
        new_name = request.form.get("new_name")

        # Load appstate JSON
        appstate = json.loads(appstate_raw)

        # Login with appstate
        client = Client("null", "null", session_cookies=appstate)

        # Change group name
        client.changeThreadTitle(new_name, thread_id=group_id, thread_type=ThreadType.GROUP)

        client.logout()
        return jsonify({"status": "success", "message": "✅ Group name changed successfully!"})

    except Exception as e:
        return jsonify({"status": "error", "message": f"❌ Failed: {str(e)}"})

# ------------------- RUN APP -------------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
