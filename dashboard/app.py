"""
Car Slave — Master Dashboard

Streamlit dashboard for controlling the robot car and monitoring
sensor data from the Raspberry Pi via the FastAPI HTTP bridge.

Usage:
    streamlit run dashboard/app.py
"""

import streamlit as st
import streamlit.components.v1 as components
import streamlit.components.v1 as components
import requests
import time
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dashboard")
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dashboard")

st.set_page_config(page_title="Car Slave Dashboard", layout="wide")

if "log_messages" not in st.session_state:
    st.session_state.log_messages = []


def app_log(level: str, msg: str):
    ts = time.strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{ts}] [{level}] {msg}")
    if len(st.session_state.log_messages) > 100:
        st.session_state.log_messages = st.session_state.log_messages[-100:]
    getattr(log, level.lower(), log.info)(msg)


if "log_messages" not in st.session_state:
    st.session_state.log_messages = []


def app_log(level: str, msg: str):
    ts = time.strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{ts}] [{level}] {msg}")
    if len(st.session_state.log_messages) > 100:
        st.session_state.log_messages = st.session_state.log_messages[-100:]
    getattr(log, level.lower(), log.info)(msg)


# -- Sidebar: Connection --------------------------------------------------

st.sidebar.title("Connection")
use_ethernet = st.sidebar.toggle("Use Ethernet", value=False, help="Connect via Ethernet on 192.168.50.2:8000")

if use_ethernet:
    pi_host = "192.168.50.2"
    pi_port = 8000
    st.sidebar.info(f"Ethernet: {pi_host}:{pi_port}")
else:
    pi_host = st.sidebar.text_input("Raspberry Pi IP", value="localhost")
    pi_port = st.sidebar.number_input("Port", value=8000, min_value=1, max_value=65535)
BASE_URL = f"http://{pi_host}:{pi_port}"
app_log("INFO", f"Dashboard started, target: {BASE_URL}")
app_log("INFO", f"Dashboard started, target: {BASE_URL}")

if st.sidebar.button("Test Connection"):
    app_log("INFO", f"Testing connection to {BASE_URL}")
    app_log("INFO", f"Testing connection to {BASE_URL}")
    try:
        r = requests.get(f"{BASE_URL}/", timeout=3)
        if r.status_code == 200:
            st.sidebar.success("Connected")
            app_log("INFO", f"Connection OK: {r.json()}")
            app_log("INFO", f"Connection OK: {r.json()}")
        else:
            st.sidebar.error(f"HTTP {r.status_code}")
            app_log("ERROR", f"HTTP {r.status_code}")
    except requests.ConnectionError as e:
            app_log("ERROR", f"HTTP {r.status_code}")
    except requests.ConnectionError as e:
        st.sidebar.error("Cannot reach the Pi. Check IP and port.")
        app_log("ERROR", f"ConnectionError: {e}")
    except requests.Timeout as e:
        app_log("ERROR", f"ConnectionError: {e}")
    except requests.Timeout as e:
        st.sidebar.error("Connection timed out.")
        app_log("ERROR", f"Timeout: {e}")
        app_log("ERROR", f"Timeout: {e}")

st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("Auto-refresh data", value=False)
refresh_rate = st.sidebar.slider(
    "Refresh interval (s)", 1, 10, 2, disabled=not auto_refresh
)

st.sidebar.divider()
with st.sidebar.expander("Debug Log", expanded=False):
    log_text = "\n".join(st.session_state.log_messages[::-1])
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("Clear Log"):
            st.session_state.log_messages = []
            log_text = ""
    with btn_col2:
        if st.button("Copy Log") and log_text:
            st.session_state._copy_log = True
    if st.session_state.get("_copy_log") and log_text:
        st.code(log_text, language=None)
        components.html(
            f"""<script>
            navigator.clipboard.writeText({repr(log_text)}).then(
                () => {{}}, () => {{}}
            );
            </script>""",
            height=0,
        )
        st.success("Copied to clipboard!")
        st.session_state._copy_log = False
    else:
        st.code(log_text, language=None)

# -- Title -----------------------------------------------------------------

st.title("Car Slave Dashboard")

col_camera, col_controls = st.columns([3, 2])

# -- Camera Feed -----------------------------------------------------------

with col_camera:
    st.header("Camera Feed")

    cam_col1, cam_col2 = st.columns(2)
    with cam_col1:
        stream_on = st.toggle("Show live stream", value=True)
    with cam_col2:
        if st.button("Snapshot"):
            app_log("INFO", f"Requesting snapshot from {BASE_URL}/camera/snapshot")
            app_log("INFO", f"Requesting snapshot from {BASE_URL}/camera/snapshot")
            try:
                r = requests.get(f"{BASE_URL}/camera/snapshot", timeout=5)
                app_log(
                    "DEBUG",
                    f"Snapshot response: status={r.status_code}, size={len(r.content)} bytes",
                )
                app_log(
                    "DEBUG",
                    f"Snapshot response: status={r.status_code}, size={len(r.content)} bytes",
                )
                if r.status_code == 200:
                    st.image(r.content, caption="Snapshot", use_container_width=True)
                else:
                    st.error(f"Snapshot failed: {r.status_code}")
                    app_log("ERROR", f"Snapshot failed: {r.status_code}")
                    app_log("ERROR", f"Snapshot failed: {r.status_code}")
            except requests.RequestException as e:
                st.error(f"Request failed: {e}")
                app_log("ERROR", f"Snapshot request failed: {e}")
                app_log("ERROR", f"Snapshot request failed: {e}")

    if stream_on:
        stream_url = f"{BASE_URL}/camera/stream"
        app_log("DEBUG", f"Stream URL: {stream_url}")
        stream_html = f"""
        <div id="stream-container" style="position:relative; width:100%; min-height:60px;">
          <img id="stream-img" src="{stream_url}" width="100%"
               style="border-radius:4px; display:none;" />
          <div id="stream-status"
               style="color:#fafafa; background:#262730; padding:12px; border-radius:4px;
                      font-family:monospace; font-size:13px;">
            Connecting to stream...
          </div>
        </div>
        <script>
          (function() {{
            const img = document.getElementById("stream-img");
            const status = document.getElementById("stream-status");
            let loaded = false;

            img.onload = function() {{
              if (!loaded) {{
                loaded = true;
                img.style.display = "block";
                status.style.display = "none";
                console.log("[stream] first frame loaded from {stream_url}");
              }}
            }};

            img.onerror = function() {{
              status.textContent = "Stream failed to load — check bridge is running at {BASE_URL}";
              status.style.color = "#ff6b6b";
              console.error("[stream] failed to load from {stream_url}");
            }};

            // Timeout: if no frame after 5s, show warning
            setTimeout(function() {{
              if (!loaded) {{
                status.textContent = "Stream timeout — no frames received from {BASE_URL}";
                status.style.color = "#ffa500";
                console.warn("[stream] timeout waiting for frames");
              }}
            }}, 5000);
          }})();
        </script>
        """
        components.html(stream_html, height=500)
    else:
        st.info("Live stream is off.")
        app_log("DEBUG", "Live stream is off")
        app_log("DEBUG", "Live stream is off")

    cam_col_a, cam_col_b = st.columns(2)
    with cam_col_a:
        if st.button("Enable Camera"):
            app_log("INFO", "Enabling camera...")
            app_log("INFO", "Enabling camera...")
            try:
                r = requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": True}, timeout=3
                )
                app_log("DEBUG", f"Enable camera response: {r.status_code} {r.text}")
                r = requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": True}, timeout=3
                )
                app_log("DEBUG", f"Enable camera response: {r.status_code} {r.text}")
                st.success("Camera enabled")
            except requests.RequestException as e:
                st.error(str(e))
                app_log("ERROR", f"Enable camera failed: {e}")
                app_log("ERROR", f"Enable camera failed: {e}")
    with cam_col_b:
        if st.button("Disable Camera"):
            app_log("INFO", "Disabling camera...")
            app_log("INFO", "Disabling camera...")
            try:
                r = requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": False}, timeout=3
                )
                app_log("DEBUG", f"Disable camera response: {r.status_code} {r.text}")
                r = requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": False}, timeout=3
                )
                app_log("DEBUG", f"Disable camera response: {r.status_code} {r.text}")
                st.warning("Camera disabled")
            except requests.RequestException as e:
                st.error(str(e))
                app_log("ERROR", f"Disable camera failed: {e}")
                app_log("ERROR", f"Disable camera failed: {e}")

# -- Controls & Sensors ----------------------------------------------------

with col_controls:
    st.header("Motor Controls")

    speed = st.slider("Speed", 0.1, 1.0, 0.5, 0.1)

    # Hold-to-drive: sends ONE /cmd_vel on press, ONE /stop on release.
    motor_html = f"""
    <style>
      .dpad {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; max-width: 280px; margin: 0 auto; }}
      .dpad button {{
        padding: 14px 0; font-size: 15px; font-weight: 600;
        border: 1px solid #444; border-radius: 6px;
        background: #262730; color: #fafafa; cursor: pointer;
        user-select: none; -webkit-user-select: none;
        touch-action: none;
      }}
      .dpad button:active, .dpad button.held {{ background: #0068c9; border-color: #0068c9; }}
      .dpad button.stop-btn {{ background: #c9302c; border-color: #c9302c; }}
      .dpad button.stop-btn:active {{ background: #a02622; }}
      .dpad .blank {{ visibility: hidden; }}
      #motor-status {{
        text-align: center; font-family: monospace; font-size: 12px;
        padding: 4px; margin-top: 6px; border-radius: 4px; min-height: 20px;
      }}
      .status-ok {{ color: #4caf50; }}
      .status-err {{ color: #ff6b6b; }}
      .status-send {{ color: #64b5f6; }}
    </style>
    <div class="dpad">
      <div class="blank"><button disabled></button></div>
      <button data-lx="{speed}" data-az="0">Forward</button>
      <div class="blank"><button disabled></button></div>

      <button data-lx="0" data-az="{speed}">Left</button>
      <button class="stop-btn" id="stopBtn">STOP</button>
      <button data-lx="0" data-az="-{speed}">Right</button>

      <div class="blank"><button disabled></button></div>
      <button data-lx="-{speed}" data-az="0">Backward</button>
      <div class="blank"><button disabled></button></div>
    </div>
    <div id="motor-status"></div>
    <script>
      (function() {{
        const BASE = "{BASE_URL}";
        const statusEl = document.getElementById("motor-status");
        let active = null;
        let cmdCount = 0;

        function setStatus(msg, cls) {{
          statusEl.textContent = msg;
          statusEl.className = cls;
          console.log("[motor] " + msg);
        }}

        function sendCmd(lx, az) {{
          cmdCount++;
          const n = cmdCount;
          setStatus("Sending cmd_vel lx=" + lx + " az=" + az + " ...", "status-send");
          fetch(BASE + "/cmd_vel", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{linear_x: parseFloat(lx), angular_z: parseFloat(az)}})
          }})
          .then(r => {{
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
          }})
          .then(data => {{
            if (n === cmdCount) setStatus("cmd_vel OK: lx=" + data.linear_x + " az=" + data.angular_z, "status-ok");
          }})
          .catch(err => {{
            setStatus("cmd_vel FAILED: " + err.message, "status-err");
            console.error("[motor] cmd_vel error:", err);
          }});
        }}

        function sendStop() {{
          cmdCount++;
          const n = cmdCount;
          setStatus("Sending stop...", "status-send");
          fetch(BASE + "/stop", {{method: "POST"}})
          .then(r => {{
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
          }})
          .then(() => {{
            if (n === cmdCount) setStatus("Stopped", "status-ok");
          }})
          .catch(err => {{
            setStatus("STOP FAILED: " + err.message, "status-err");
            console.error("[motor] stop error:", err);
          }});
        }}

        function startDrive(btn) {{
          if (active) return;
          active = btn;
          btn.classList.add("held");
          sendCmd(btn.dataset.lx, btn.dataset.az);
        }}

        function stopDrive() {{
          if (!active) return;
          active.classList.remove("held");
          active = null;
          sendStop();
        }}

        document.querySelectorAll(".dpad button[data-lx]").forEach(btn => {{
          btn.addEventListener("mousedown", (e) => {{ e.preventDefault(); startDrive(btn); }});
          btn.addEventListener("touchstart", (e) => {{ e.preventDefault(); startDrive(btn); }});
        }});

        document.addEventListener("mouseup", stopDrive);
        document.addEventListener("touchend", stopDrive);
        document.addEventListener("touchcancel", stopDrive);

        document.getElementById("stopBtn").addEventListener("click", sendStop);
        document.getElementById("stopBtn").addEventListener("touchstart", (e) => {{ e.preventDefault(); sendStop(); }});

        // Initial connectivity check
        fetch(BASE + "/", {{method: "GET"}})
          .then(r => {{ if (r.ok) setStatus("Connected to " + BASE, "status-ok"); else throw new Error("HTTP " + r.status); }})
          .catch(err => {{ setStatus("Cannot reach " + BASE + ": " + err.message, "status-err"); }});
      }})();
    </script>
    """
    st.components.v1.html(motor_html, height=270)

    st.divider()

    with st.expander("Custom Velocity Command"):
        custom_linear = st.slider("Linear X", -1.0, 1.0, 0.0, 0.05, key="custom_lin")
        custom_angular = st.slider("Angular Z", -1.0, 1.0, 0.0, 0.05, key="custom_ang")
        if st.button("Send Custom Command"):
            app_log(
                "INFO",
                f"Sending custom cmd_vel: linear={custom_linear}, angular={custom_angular}",
            )
            app_log(
                "INFO",
                f"Sending custom cmd_vel: linear={custom_linear}, angular={custom_angular}",
            )
            try:
                r = requests.post(
                r = requests.post(
                    f"{BASE_URL}/cmd_vel",
                    json={"linear_x": custom_linear, "angular_z": custom_angular},
                    timeout=2,
                )
                app_log("DEBUG", f"cmd_vel response: {r.status_code} {r.text}")
                app_log("DEBUG", f"cmd_vel response: {r.status_code} {r.text}")
                st.success(f"Sent: linear={custom_linear}, angular={custom_angular}")
            except requests.RequestException as e:
            except requests.RequestException as e:
                st.error("Failed to send command")
                app_log("ERROR", f"cmd_vel failed: {e}")
                app_log("ERROR", f"cmd_vel failed: {e}")

    st.divider()

    # -- Ultrasonic Distance -----------------------------------------------
    st.header("Ultrasonic Distance")

    distance_placeholder = st.empty()

    def fetch_distance():
        try:
            r = requests.get(f"{BASE_URL}/distance", timeout=3)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        return None

    if st.button("Refresh Distance", key="refresh_distance"):
        app_log("INFO", "Fetching distance...")
        app_log("INFO", "Fetching distance...")
        data = fetch_distance()
        if not data:
            distance_placeholder.warning("Could not fetch distance data")
            app_log("ERROR", "Failed to fetch distance data")
        else:
            app_log("DEBUG", f"Distance data: {data}")
            app_log("ERROR", "Failed to fetch distance data")
        else:
            app_log("DEBUG", f"Distance data: {data}")

    data = fetch_distance()
    if data:
        distance = data.get("distance_cm", 0)
        sensor_type = data.get("sensor_type", "unknown")
        distance_placeholder.metric(label="Distance", value=f"{distance:.1f} cm")
        st.caption(f"Sensor: {sensor_type}")
    else:
        distance_placeholder.info("Click refresh or enable auto-refresh")

    st.divider()

    # -- System Status -----------------------------------------------------
    st.header("System Status")

    status_placeholder = st.empty()

    if st.button("Refresh Status", key="refresh_status"):
        app_log("INFO", "Fetching system status...")
        app_log("INFO", "Fetching system status...")
        try:
            r = requests.get(f"{BASE_URL}/status", timeout=3)
            if r.status_code == 200:
                status = r.json()
                app_log("DEBUG", f"Status: {status}")
                app_log("DEBUG", f"Status: {status}")
                with status_placeholder.container():
                    s1, s2, s3 = st.columns(3)
                    s1.metric(
                        "Camera", "Active" if status["camera"]["active"] else "Inactive"
                    )
                    s2.metric(
                        "Distance",
                        f"{status['ultrasonic']['latest_distance_cm']:.1f} cm",
                    )
                    s1.metric(
                        "Camera", "Active" if status["camera"]["active"] else "Inactive"
                    )
                    s2.metric(
                        "Distance",
                        f"{status['ultrasonic']['latest_distance_cm']:.1f} cm",
                    )
                    motor = status.get("motor", {})
                    s3.metric("GPIO", "Yes" if motor.get("gpio_available") else "No")
            else:
                status_placeholder.error(f"HTTP {r.status_code}")
                app_log("ERROR", f"Status fetch failed: HTTP {r.status_code}")
                app_log("ERROR", f"Status fetch failed: HTTP {r.status_code}")
        except requests.RequestException as e:
            status_placeholder.error(f"Cannot reach Pi: {e}")
            app_log("ERROR", f"Status fetch failed: {e}")
            app_log("ERROR", f"Status fetch failed: {e}")

# -- Auto-refresh ----------------------------------------------------------

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
