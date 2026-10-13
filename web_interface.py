"""
DISHA — Remote Web Interface
Runs on 0.0.0.0:WEB_PORT when DISHA_WEB_ENABLED=true.
Provides a modern mobile-friendly HTML chat UI + REST API.
Secured by bearer token (DISHA_WEB_TOKEN in .env).
"""

import datetime
import os
import secrets
import socket
import threading
from typing import Callable, Optional

from flask import Flask, abort, jsonify, render_template_string, request
import psutil

from config import WEB_ENABLED, WEB_HOST, WEB_PORT, WEB_TOKEN
import gemini_client

_app = Flask(__name__)
_route_fn: Optional[Callable[[str], str]] = None
_server_thread: Optional[threading.Thread] = None


def get_local_ip() -> str:
    """Determine the LAN IP address for local network access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _check_auth():
    """Validate bearer token from header or query string using constant-time comparison."""
    if not WEB_TOKEN:
        abort(403, description="Remote access disabled: DISHA_WEB_TOKEN is not configured.")

    # Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if secrets.compare_digest(token, WEB_TOKEN):
            return

    # Check X-Token header
    token = request.headers.get("X-Token", "").strip()
    if token and secrets.compare_digest(token, WEB_TOKEN):
        return

    # Check query parameter ?token=<token>
    token = request.args.get("token", "").strip()
    if token and secrets.compare_digest(token, WEB_TOKEN):
        return

    # Check json payload { "token": "..." }
    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = str(data.get("token", "")).strip()
        if token and secrets.compare_digest(token, WEB_TOKEN):
            return

    abort(401)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>DISHA — Mobile Companion</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: #1e1e2e;
      color: #cdd6f4;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    header {
      background: #181825;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #313244;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo {
      width: 32px;
      height: 32px;
      background: #a6e3a1;
      color: #11111b;
      font-weight: 900;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
    }
    .title {
      font-weight: 700;
      font-size: 16px;
      color: #89b4fa;
      letter-spacing: 0.5px;
    }
    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #a6adc8;
      background: #313244;
      padding: 4px 10px;
      border-radius: 12px;
    }
    .dot {
      width: 8px;
      height: 8px;
      background: #a6e3a1;
      border-radius: 50%;
      display: inline-block;
    }
    #chat-container {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }
    .msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 14px;
      line-height: 1.45;
      word-break: break-word;
      animation: fadeIn 0.2s ease-in-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .msg.user {
      align-self: flex-end;
      background: #89b4fa;
      color: #11111b;
      border-bottom-right-radius: 2px;
      font-weight: 500;
    }
    .msg.bot {
      align-self: flex-start;
      background: #313244;
      color: #cdd6f4;
      border-bottom-left-radius: 2px;
      border: 1px solid #45475a;
    }
    .msg.system {
      align-self: center;
      background: rgba(250, 179, 135, 0.15);
      color: #fab387;
      font-size: 12px;
      padding: 4px 12px;
      border-radius: 10px;
    }
    .timestamp {
      font-size: 10px;
      opacity: 0.7;
      margin-top: 4px;
      text-align: right;
    }
    .quick-chips {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 8px 16px;
      background: #181825;
      border-top: 1px solid #313244;
      white-space: nowrap;
    }
    .chip {
      background: #313244;
      color: #cdd6f4;
      padding: 6px 12px;
      border-radius: 16px;
      font-size: 12px;
      border: 1px solid #45475a;
      cursor: pointer;
      user-select: none;
    }
    .chip:active {
      background: #89b4fa;
      color: #11111b;
    }
    footer {
      background: #181825;
      padding: 12px 16px;
      display: flex;
      gap: 10px;
      border-top: 1px solid #313244;
    }
    #input-box {
      flex: 1;
      background: #313244;
      border: 1px solid #45475a;
      color: #cdd6f4;
      padding: 12px 16px;
      border-radius: 24px;
      font-size: 15px;
      outline: none;
    }
    #input-box:focus {
      border-color: #89b4fa;
    }
    #btn-send {
      background: #a6e3a1;
      color: #11111b;
      border: none;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      cursor: pointer;
      font-weight: bold;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      transition: transform 0.1s;
    }
    #btn-send:active {
      transform: scale(0.92);
    }
    .token-modal {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.7);
      align-items: center;
      justify-content: center;
      z-index: 100;
    }
    .token-card {
      background: #1e1e2e;
      border: 1px solid #45475a;
      padding: 24px;
      border-radius: 16px;
      max-width: 320px;
      width: 90%;
      text-align: center;
    }
    .token-input {
      width: 100%;
      padding: 10px;
      background: #313244;
      border: 1px solid #45475a;
      color: #cdd6f4;
      border-radius: 8px;
      margin: 12px 0;
      font-size: 14px;
      text-align: center;
    }
    .btn-token {
      background: #89b4fa;
      color: #11111b;
      border: none;
      padding: 8px 20px;
      border-radius: 8px;
      font-weight: bold;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="logo">D</div>
      <div>
        <div class="title">DISHA Mobile</div>
        <div style="font-size: 10px; color: #a6adc8;" id="host-ip">Local Companion</div>
      </div>
    </div>
    <div class="status-badge" onclick="promptToken()">
      <span class="dot" id="status-dot"></span>
      <span id="status-text">Ready</span>
    </div>
  </header>

  <div id="chat-container">
    <div class="msg bot">
      Hello! I'm DISHA on your local network. Ask me questions, control apps, or check status.
      <div class="timestamp">Just now</div>
    </div>
  </div>

  <div class="quick-chips">
    <div class="chip" onclick="quickSend('what time is it')">🕒 Time</div>
    <div class="chip" onclick="quickSend('battery')">🔋 Battery</div>
    <div class="chip" onclick="quickSend('ram usage')">💾 RAM</div>
    <div class="chip" onclick="quickSend('what did i copy')">📋 Clipboard</div>
  </div>

  <footer>
    <input type="text" id="input-box" placeholder="Ask DISHA anything..." autocomplete="off">
    <button id="btn-send" onclick="sendMessage()">➤</button>
  </footer>

  <div class="token-modal" id="token-modal">
    <div class="token-card">
      <h3 style="color:#89b4fa; margin-bottom:8px;">Access Token</h3>
      <p style="font-size:12px; color:#a6adc8;">Enter DISHA_WEB_TOKEN to authenticate:</p>
      <input type="password" id="modal-token-input" class="token-input" placeholder="Token">
      <button class="btn-token" onclick="saveToken()">Save Token</button>
    </div>
  </div>

  <script>
    let token = localStorage.getItem("disha_token") || "";
    const chatContainer = document.getElementById("chat-container");
    const inputBox = document.getElementById("input-box");

    // Check token from URL param if present
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has("token")) {
      token = urlParams.get("token");
      localStorage.setItem("disha_token", token);
    }

    function promptToken() {
      document.getElementById("modal-token-input").value = token;
      document.getElementById("token-modal").style.display = "flex";
    }

    function saveToken() {
      token = document.getElementById("modal-token-input").value.trim();
      localStorage.setItem("disha_token", token);
      document.getElementById("token-modal").style.display = "none";
      updateStatus();
    }

    function getTimeStr() {
      const now = new Date();
      return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function escapeHtml(str) {
      const p = document.createElement("p");
      p.textContent = str;
      return p.innerHTML;
    }

    function appendMessage(role, text) {
      const div = document.createElement("div");
      div.className = "msg " + role;
      const safe = escapeHtml(text).replace(/\\n/g, "<br>");
      div.innerHTML = safe + '<div class="timestamp">' + getTimeStr() + '</div>';
      chatContainer.appendChild(div);
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    async function sendMessage() {
      const query = inputBox.value.trim();
      if (!query) return;

      inputBox.value = "";
      appendMessage("user", query);

      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;

      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: headers,
          body: JSON.stringify({ query: query })
        });

        if (res.status === 401) {
          appendMessage("system", "⚠️ Unauthorized. Please click status to enter token.");
          promptToken();
          return;
        }

        const data = await res.json();
        if (data.response) {
          appendMessage("bot", data.response);
        } else if (data.error) {
          appendMessage("system", "Error: " + data.error);
        }
      } catch (err) {
        appendMessage("system", "Network error: unable to reach DISHA.");
      }
    }

    function quickSend(text) {
      inputBox.value = text;
      sendMessage();
    }

    inputBox.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendMessage();
    });

    async function updateStatus() {
      const headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      try {
        const res = await fetch("/api/status", { headers });
        if (res.ok) {
          const data = await res.json();
          let txt = "Ready";
          if (data.battery !== null) {
            txt = data.battery + "%" + (data.charging ? " ⚡" : "");
          }
          document.getElementById("status-text").innerText = txt;
          document.getElementById("status-dot").style.background = "#a6e3a1";
        } else if (res.status === 401) {
          document.getElementById("status-text").innerText = "Locked";
          document.getElementById("status-dot").style.background = "#fab387";
        }
      } catch (e) {
        document.getElementById("status-text").innerText = "Offline";
        document.getElementById("status-dot").style.background = "#f38ba8";
      }
    }

    setInterval(updateStatus, 15000);
    updateStatus();
  </script>
</body>
</html>
"""


@_app.route("/")
def index():
    """Serve the modern web client."""
    return render_template_string(HTML_TEMPLATE)


@_app.route("/api/ask", methods=["POST"])
def api_ask():
    """Handle text queries from remote client."""
    _check_auth()
    data = request.get_json(force=True, silent=True) or {}
    query = str(data.get("query", "")).strip()[:2000]
    if not query:
        return jsonify({"error": "empty query"}), 400

    if _route_fn is None:
        return jsonify({"error": "router not initialized"}), 503

    try:
        response = _route_fn(query)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@_app.route("/api/status", methods=["GET"])
def api_status():
    """Provide machine telemetry (battery, charging, time, online status)."""
    _check_auth()
    batt = psutil.sensors_battery()
    return jsonify({
        "battery": int(batt.percent) if batt else None,
        "charging": batt.power_plugged if batt else None,
        "time": datetime.datetime.now().isoformat(),
        "online": gemini_client.is_online(),
    })


def init(route_fn: Callable[[str], str]) -> None:
    """
    Start the remote Flask server in a daemon thread if WEB_ENABLED is true.
    Injected with the same route_request function used by main.py.
    """
    global _route_fn, _server_thread
    _route_fn = route_fn

    if not WEB_ENABLED:
        return

    def run_server():
        try:
            # Silence default Werkzeug logging in background
            import logging
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.ERROR)

            _app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)
        except Exception as e:
            print(f"[Web Interface] Server error: {e}")

    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()
    local_ip = get_local_ip()
    print(f"[Web Interface] Started on http://{local_ip}:{WEB_PORT}")
