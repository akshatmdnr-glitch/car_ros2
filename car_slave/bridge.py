"""
FastAPI HTTP → ROS 2 Bridge Server.

Runs on the Raspberry Pi and exposes REST endpoints for the master
dashboard to:
  - Send motor commands (POST /cmd_vel)
  - Get ultrasonic distance readings (GET /distance)
  - Stream MJPEG video (GET /camera/stream)
  - Get camera snapshot (GET /camera/snapshot)
  - Enable/disable camera (POST /camera/enable)
  - Get system status (GET /status)

This server runs in the same process as the ROS 2 nodes, giving it
direct access to node internals (e.g., latest camera frame) while
also publishing/subscribing to ROS 2 topics.
"""

import argparse
import asyncio
import fcntl
import json
import os
import socket
import struct
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, Float32, String

from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from car_slave.nodes.camera_node import CameraNode
from car_slave.nodes.uv_sensor_node import UltrasonicSensorNode
from car_slave.nodes.motor_controller_node import MotorControllerNode


# ── Pydantic models for request validation ──────────────────────────


class CmdVelRequest(BaseModel):
    linear_x: float = Field(0.0, ge=-1.0, le=1.0, description="Forward/backward speed")
    angular_z: float = Field(0.0, ge=-1.0, le=1.0, description="Rotation speed")


class CameraEnableRequest(BaseModel):
    enabled: bool


# ── Bridge Node (subscribes to topics for API readback) ─────────────


class BridgeNode(Node):
    """Lightweight node that subscribes to topics for HTTP API readback."""

    def __init__(self):
        super().__init__("fastapi_bridge")

        self._cmd_vel_pub = self.create_publisher(Twist, "cmd_vel", 10)
        self._camera_enable_pub = self.create_publisher(Bool, "camera/enable", 10)

        # Subscribe to sensor readings for API
        self._latest_distance: float = 0.0
        self._distance_sub = self.create_subscription(
            Float32, "ultrasonic/distance", self._distance_callback, 10
        )

        self._latest_motor_status: dict = {}
        self._motor_sub = self.create_subscription(
            String, "motor/status", self._motor_status_callback, 10
        )

        self.get_logger().info("FastAPI bridge node started")

    def _distance_callback(self, msg: Float32):
        self._latest_distance = msg.data

    def _motor_status_callback(self, msg: String):
        try:
            self._latest_motor_status = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def publish_cmd_vel(self, linear_x: float, angular_z: float):
        msg = Twist()
        msg.linear.x = linear_x
        msg.angular.z = angular_z
        self._cmd_vel_pub.publish(msg)

    def publish_camera_enable(self, enabled: bool):
        msg = Bool()
        msg.data = enabled
        self._camera_enable_pub.publish(msg)


# ── Global node references (set during startup) ─────────────────────

camera_node: CameraNode | None = None
ultrasonic_node: UltrasonicSensorNode | None = None
motor_node: MotorControllerNode | None = None
bridge_node: BridgeNode | None = None
network_mode: str = "any"
server_host: str = "0.0.0.0"
server_port: int = 8000


def _get_interface_ipv4(interface_name: str) -> str | None:
    """Return the IPv4 address for a network interface on Linux."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        request = struct.pack("256s", interface_name[:15].encode("utf-8"))
        response = fcntl.ioctl(sock.fileno(), 0x8915, request)
        return socket.inet_ntoa(response[20:24])
    except OSError:
        return None
    finally:
        sock.close()


def _detect_interface(preferred_name: str, prefixes: tuple[str, ...]) -> str | None:
    """Return a usable interface name, preferring an explicit name."""
    candidates = []
    if preferred_name:
        candidates.append(preferred_name)

    try:
        for interface_name in os.listdir("/sys/class/net"):
            if interface_name == preferred_name:
                continue
            if interface_name.startswith(prefixes):
                candidates.append(interface_name)
    except OSError:
        pass

    for interface_name in candidates:
        if _get_interface_ipv4(interface_name) is not None:
            return interface_name
    return None


def _resolve_server_binding(
    mode: str, ethernet_iface: str, wifi_iface: str
) -> tuple[str, str | None]:
    """Resolve which host/IP FastAPI should bind to."""
    if mode == "any":
        return "0.0.0.0", None

    if mode == "ethernet":
        interface_name = _detect_interface(ethernet_iface, ("eth", "en"))
    else:
        interface_name = _detect_interface(wifi_iface, ("wlan", "wl"))

    if interface_name is None:
        raise RuntimeError(f"No active {mode} interface with an IPv4 address was found")

    interface_ip = _get_interface_ipv4(interface_name)
    if interface_ip is None:
        raise RuntimeError(
            f"Could not resolve IPv4 address for interface '{interface_name}'"
        )

    return interface_ip, interface_name


def _parse_args(args=None):
    parser = argparse.ArgumentParser(description="Car Slave ROS 2 FastAPI bridge")
    parser.add_argument(
        "--network-mode",
        choices=("any", "ethernet", "wifi"),
        default="any",
        help="Accept requests on all interfaces, Ethernet only, or Wi-Fi only",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port for the FastAPI bridge",
    )
    parser.add_argument(
        "--ethernet-iface",
        default="eth0",
        help="Preferred Ethernet interface name when --network-mode=ethernet",
    )
    parser.add_argument(
        "--wifi-iface",
        default="wlan0",
        help="Preferred Wi-Fi interface name when --network-mode=wifi",
    )
    return parser.parse_known_args(args=args)


# ── FastAPI app ──────────────────────────────────────────────────────

app = FastAPI(
    title="Car Slave - ROS 2 HTTP Bridge",
    description="REST API bridge between master dashboard and ROS 2 nodes on the Raspberry Pi",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", summary="Health check")
async def root():
    return {"status": "ok", "node": "car_slave", "timestamp": time.time()}


@app.get("/status", summary="Get full system status")
async def get_status():
    return {
        "network": {
            "mode": network_mode,
            "bind_host": server_host,
            "port": server_port,
        },
        "camera": {
            "active": camera_node is not None and camera_node._enabled,
            "has_hardware": camera_node is not None and camera_node._camera is not None,
        },
        "ultrasonic": {
            "type": ultrasonic_node.active_sensor_type
            if ultrasonic_node
            else "unavailable",
            "latest_distance_cm": bridge_node._latest_distance if bridge_node else None,
        },
        "motor": bridge_node._latest_motor_status if bridge_node else {},
        "timestamp": time.time(),
    }


# ── Motor control ───────────────────────────────────────────────────


@app.post("/cmd_vel", summary="Send velocity command to motors")
async def cmd_vel(req: CmdVelRequest):
    if bridge_node is None:
        return JSONResponse(status_code=503, content={"error": "Bridge not ready"})
    bridge_node.publish_cmd_vel(req.linear_x, req.angular_z)
    return {"status": "ok", "linear_x": req.linear_x, "angular_z": req.angular_z}


@app.post("/stop", summary="Emergency stop")
async def stop():
    if bridge_node is None:
        return JSONResponse(status_code=503, content={"error": "Bridge not ready"})
    bridge_node.publish_cmd_vel(0.0, 0.0)
    return {"status": "stopped"}


# ── Ultrasonic Sensor ────────────────────────────────────────────────


@app.get("/distance", summary="Get latest ultrasonic distance reading (cm)")
async def get_distance():
    if bridge_node is None:
        return JSONResponse(status_code=503, content={"error": "Bridge not ready"})
    return {
        "distance_cm": bridge_node._latest_distance,
        "sensor_type": ultrasonic_node.active_sensor_type
        if ultrasonic_node
        else "unavailable",
        "timestamp": time.time(),
    }


# ── Camera ───────────────────────────────────────────────────────────


@app.get("/camera/snapshot", summary="Get a single JPEG frame")
async def camera_snapshot():
    if camera_node is None:
        return JSONResponse(status_code=503, content={"error": "Camera not ready"})
    frame = camera_node.get_latest_frame()
    if frame is None:
        return JSONResponse(status_code=503, content={"error": "No frame available"})
    return Response(content=frame, media_type="image/jpeg")


async def _mjpeg_generator():
    """Async generator that yields MJPEG frames."""
    while True:
        if camera_node is not None:
            frame = camera_node.get_latest_frame()
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        await asyncio.sleep(1.0 / 30)  # ~30 fps


@app.get("/camera/stream", summary="MJPEG video stream")
async def camera_stream():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/camera/enable", summary="Enable or disable camera streaming")
async def camera_enable(req: CameraEnableRequest):
    if bridge_node is None:
        return JSONResponse(status_code=503, content={"error": "Bridge not ready"})
    bridge_node.publish_camera_enable(req.enabled)
    return {"status": "ok", "enabled": req.enabled}


# ── ROS 2 spin in background thread ─────────────────────────────────


def _ros_spin(executor: MultiThreadedExecutor):
    """Spin all ROS 2 nodes in a background thread."""
    try:
        executor.spin()
    except Exception:
        pass


def main(args=None):
    global \
        camera_node, \
        ultrasonic_node, \
        motor_node, \
        bridge_node, \
        network_mode, \
        server_host, \
        server_port

    parsed_args, ros_args = _parse_args(args)
    network_mode = parsed_args.network_mode
    server_port = parsed_args.port
    server_host, bound_interface = _resolve_server_binding(
        parsed_args.network_mode,
        parsed_args.ethernet_iface,
        parsed_args.wifi_iface,
    )

    rclpy.init(args=ros_args)

    # Create all nodes
    camera_node = CameraNode()
    ultrasonic_node = UltrasonicSensorNode()
    motor_node = MotorControllerNode()
    bridge_node = BridgeNode()

    # Multi-threaded executor for all nodes
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(camera_node)
    executor.add_node(ultrasonic_node)
    executor.add_node(motor_node)
    executor.add_node(bridge_node)

    # Spin ROS 2 in background
    ros_thread = threading.Thread(target=_ros_spin, args=(executor,), daemon=True)
    ros_thread.start()

    # Start FastAPI server (blocking)
    bridge_node.get_logger().info(
        f"Starting FastAPI server on {server_host}:{server_port} (mode={network_mode}"
        f"{', interface=' + bound_interface if bound_interface else ''})"
    )
    try:
        uvicorn.run(app, host=server_host, port=server_port, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        camera_node.destroy_node()
        ultrasonic_node.destroy_node()
        motor_node.destroy_node()
        bridge_node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()