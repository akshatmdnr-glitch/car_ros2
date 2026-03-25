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

import asyncio
import threading
import time
import json
import logging
import socket
import netifaces

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
from car_slave.nodes.gyro_sensor_node import GyroSensorNode
from starlette.requests import Request


# ── Logging setup ────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("network")


def _get_interface_subnet(iface: str) -> str | None:
    """Get the subnet prefix for a network interface (e.g., '192.168.1')."""
    try:
        addrs = netifaces.ifaddresses(iface)
        if netifaces.AF_INET in addrs:
            ip = addrs[netifaces.AF_INET][0].get("addr", "")
            parts = ip.split(".")
            if len(parts) == 4:
                return ".".join(parts[:3])
    except Exception:
        pass
    return None


def _detect_network_source(client_ip: str) -> str:
    """Detect if client IP is on Ethernet or WiFi subnet."""
    for iface in ["eth0", "enp0s3", "enp2s0"]:
        subnet = _get_interface_subnet(iface)
        if subnet and client_ip.startswith(subnet + "."):
            return f"ethernet ({iface})"
    for iface in ["wlan0", "wlp3s0"]:
        subnet = _get_interface_subnet(iface)
        if subnet and client_ip.startswith(subnet + "."):
            return f"wifi ({iface})"
    return "unknown"


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

        self._latest_gyro_status: dict = {}
        self._gyro_sub = self.create_subscription(
            String, "gyro/status", self._gyro_status_callback, 10
        )

        self.get_logger().info("FastAPI bridge node started")

    def _distance_callback(self, msg: Float32):
        self._latest_distance = msg.data

    def _motor_status_callback(self, msg: String):
        try:
            self._latest_motor_status = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def _gyro_status_callback(self, msg: String):
        try:
            self._latest_gyro_status = json.loads(msg.data)
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
gyro_node: GyroSensorNode | None = None
bridge_node: BridgeNode | None = None


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


@app.middleware("http")
async def log_network_source(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    network_source = _detect_network_source(client_ip)
    logger.info(
        f"Request {request.method} {request.url.path} from {client_ip} via {network_source}"
    )
    response = await call_next(request)
    return response


@app.get("/", summary="Health check")
async def root():
    return {"status": "ok", "node": "car_slave", "timestamp": time.time()}


@app.get("/status", summary="Get full system status")
async def get_status():
    return {
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
        "gyro": bridge_node._latest_gyro_status if bridge_node else {},
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


# ── Gyro Sensor ────────────────────────────────────────────────────────


@app.get("/gyro", summary="Get latest gyroscope/IMU readings")
async def get_gyro():
    if bridge_node is None:
        return JSONResponse(status_code=503, content={"error": "Bridge not ready"})
    return {
        "gyro_status": bridge_node._latest_gyro_status,
        "sensor_type": gyro_node.active_sensor_type if gyro_node else "unavailable",
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
    global camera_node, ultrasonic_node, motor_node, gyro_node, bridge_node

    rclpy.init(args=args)

    camera_node = CameraNode()
    ultrasonic_node = UltrasonicSensorNode()
    motor_node = MotorControllerNode()
    gyro_node = GyroSensorNode()
    bridge_node = BridgeNode()

    executor = MultiThreadedExecutor(num_threads=5)
    executor.add_node(camera_node)
    executor.add_node(ultrasonic_node)
    executor.add_node(motor_node)
    executor.add_node(gyro_node)
    executor.add_node(bridge_node)

    ros_thread = threading.Thread(target=_ros_spin, args=(executor,), daemon=True)
    ros_thread.start()

    bridge_node.get_logger().info("Starting FastAPI server on 0.0.0.0:8000")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        camera_node.destroy_node()
        ultrasonic_node.destroy_node()
        motor_node.destroy_node()
        gyro_node.destroy_node()
        bridge_node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
