"""
Car Slave — Master Dashboard

Streamlit dashboard for controlling the robot car and monitoring
sensor data from the Raspberry Pi via the FastAPI HTTP bridge.

Usage:
    streamlit run dashboard/app.py
"""

import streamlit as st
import requests
import time

st.set_page_config(page_title="Car Slave Dashboard", layout="wide")

if "network_target" not in st.session_state:
    st.session_state.network_target = "Ethernet"
if "ethernet_host" not in st.session_state:
    st.session_state.ethernet_host = "localhost"
if "wifi_host" not in st.session_state:
    st.session_state.wifi_host = "localhost"

# -- Sidebar: Connection --------------------------------------------------

st.sidebar.title("Connection")
network_target = st.sidebar.toggle(
    "Use Wi-Fi connection",
    value=st.session_state.network_target == "Wi-Fi",
)
st.session_state.network_target = "Wi-Fi" if network_target else "Ethernet"
selected_mode = "wifi" if network_target else "ethernet"

ethernet_host = st.sidebar.text_input(
    "Ethernet IP",
    key="ethernet_host",
    disabled=st.session_state.network_target != "Ethernet",
)
wifi_host = st.sidebar.text_input(
    "Wi-Fi IP",
    key="wifi_host",
    disabled=st.session_state.network_target != "Wi-Fi",
)

pi_host = (
    st.session_state.wifi_host
    if st.session_state.network_target == "Wi-Fi"
    else st.session_state.ethernet_host
)
pi_port = st.sidebar.number_input("Port", value=8000, min_value=1, max_value=65535)
BASE_URL = f"http://{pi_host}:{pi_port}"
st.sidebar.caption(
    f"Active target: {st.session_state.network_target} ({pi_host}:{pi_port})"
)

if st.sidebar.button("Apply Bridge Network Mode"):
    try:
        r = requests.post(
            f"{BASE_URL}/network/mode",
            json={"mode": selected_mode},
            timeout=3,
        )
        if r.status_code == 200:
            st.sidebar.success(f"Bridge now accepts {selected_mode} requests")
        else:
            detail = r.json().get("error", f"HTTP {r.status_code}")
            st.sidebar.error(detail)
    except requests.RequestException as e:
        st.sidebar.error(f"Failed to update bridge mode: {e}")

if st.sidebar.button("Test Connection"):
    try:
        r = requests.get(f"{BASE_URL}/", timeout=3)
        if r.status_code == 200:
            st.sidebar.success("Connected")
        else:
            st.sidebar.error(f"HTTP {r.status_code}")
    except requests.ConnectionError:
        st.sidebar.error("Cannot reach the Pi. Check IP and port.")
    except requests.Timeout:
        st.sidebar.error("Connection timed out.")

st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("Auto-refresh data", value=False)
refresh_rate = st.sidebar.slider(
    "Refresh interval (s)", 1, 10, 2, disabled=not auto_refresh
)

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
            try:
                r = requests.get(f"{BASE_URL}/camera/snapshot", timeout=5)
                if r.status_code == 200:
                    st.image(r.content, caption="Snapshot", use_container_width=True)
                else:
                    st.error(f"Snapshot failed: {r.status_code}")
            except requests.RequestException as e:
                st.error(f"Request failed: {e}")

    if stream_on:
        stream_url = f"{BASE_URL}/camera/stream"
        st.markdown(
            f'<img src="{stream_url}" width="100%" style="border-radius: 4px;" />',
            unsafe_allow_html=True,
        )
    else:
        st.info("Live stream is off.")

    cam_col_a, cam_col_b = st.columns(2)
    with cam_col_a:
        if st.button("Enable Camera"):
            try:
                requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": True}, timeout=3
                )
                st.success("Camera enabled")
            except requests.RequestException as e:
                st.error(str(e))
    with cam_col_b:
        if st.button("Disable Camera"):
            try:
                requests.post(
                    f"{BASE_URL}/camera/enable", json={"enabled": False}, timeout=3
                )
                st.warning("Camera disabled")
            except requests.RequestException as e:
                st.error(str(e))

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
    <script>
      (function() {{
        const BASE = "{BASE_URL}";
        let active = null;

        function sendCmd(lx, az) {{
          fetch(BASE + "/cmd_vel", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{linear_x: parseFloat(lx), angular_z: parseFloat(az)}})
          }}).catch(() => {{}});
        }}

        function sendStop() {{
          fetch(BASE + "/stop", {{method: "POST"}}).catch(() => {{}});
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
      }})();
    </script>
    """
    st.components.v1.html(motor_html, height=220)

    st.divider()

    with st.expander("Custom Velocity Command"):
        custom_linear = st.slider("Linear X", -1.0, 1.0, 0.0, 0.05, key="custom_lin")
        custom_angular = st.slider("Angular Z", -1.0, 1.0, 0.0, 0.05, key="custom_ang")
        if st.button("Send Custom Command"):
            try:
                requests.post(
                    f"{BASE_URL}/cmd_vel",
                    json={"linear_x": custom_linear, "angular_z": custom_angular},
                    timeout=2,
                )
                st.success(f"Sent: linear={custom_linear}, angular={custom_angular}")
            except requests.RequestException:
                st.error("Failed to send command")

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
        data = fetch_distance()
        if not data:
            distance_placeholder.warning("Could not fetch distance data")

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
        try:
            r = requests.get(f"{BASE_URL}/status", timeout=3)
            if r.status_code == 200:
                status = r.json()
                with status_placeholder.container():
                    s1, s2, s3 = st.columns(3)
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
        except requests.RequestException as e:
            status_placeholder.error(f"Cannot reach Pi: {e}")

# -- Auto-refresh ----------------------------------------------------------

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
