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
    }
    .container {
      background: #2c2c2c;
      padding: 30px;
      border-radius: 10px;
      width: 400px;
      text-align: center;
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
