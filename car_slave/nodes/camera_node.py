"""
ROS 2 Camera Node using Picamera2.

Publishes compressed JPEG frames to /camera/image/compressed
and provides an MJPEG stream endpoint via the FastAPI bridge.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool
import cv2
import numpy as np
import threading
import time

# picamera2 is available on the Raspberry Pi
try:
    from picamera2 import Picamera2
    HAS_PICAMERA2 = True
except ImportError:
    HAS_PICAMERA2 = False


class CameraNode(Node):
    def __init__(self):
        super().__init__('camera_node')

        # Declare parameters
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30)
        self.declare_parameter('jpeg_quality', 80)
        self.declare_parameter('autofocus_mode', 'continuous')

        self._width = self.get_parameter('width').value
        self._height = self.get_parameter('height').value
        self._fps = self.get_parameter('fps').value
        self._jpeg_quality = self.get_parameter('jpeg_quality').value
        self._autofocus_mode = self.get_parameter('autofocus_mode').value

        # Publisher for compressed images (for ROS topic consumers)
        self._pub = self.create_publisher(CompressedImage, 'camera/image/compressed', 10)

        # Subscription to enable/disable streaming
        self._sub = self.create_subscription(Bool, 'camera/enable', self._enable_callback, 10)

        # Internal state
        self._enabled = True
        self._latest_frame: bytes | None = None
        self._frame_lock = threading.Lock()
        self._camera = None

        self._init_camera()

        # Timer to capture and publish at configured FPS
        period = 1.0 / self._fps
        self._timer = self.create_timer(period, self._capture_callback)

        self.get_logger().info(
            f'Camera node started: {self._width}x{self._height} @ {self._fps}fps'
        )

    def _init_camera(self):
        if not HAS_PICAMERA2:
            self.get_logger().warn('picamera2 not available — using test pattern')
            return

        try:
            camera_info = Picamera2.global_camera_info()
            if not camera_info:
                self.get_logger().warn('No camera detected — using test pattern')
                return

            self._camera = Picamera2()
            config = self._camera.create_preview_configuration(
                main={'size': (self._width, self._height), 'format': 'RGB888'}
            )
            self._camera.configure(config)

            try:
                from libcamera import controls
                af_modes = {
                    'continuous': controls.AfModeEnum.Continuous,
                    'manual': controls.AfModeEnum.Manual,
                    'auto': controls.AfModeEnum.Auto,
                }
                af_mode = af_modes.get(self._autofocus_mode, controls.AfModeEnum.Continuous)
                self._camera.set_controls({'AfMode': af_mode})
            except Exception as e:
                self.get_logger().warn(f'Autofocus setup skipped: {e}')

            self._camera.start()
        except Exception as e:
            self.get_logger().warn(f'Camera init failed: {e} — using test pattern')
            self._camera = None

    def _capture_callback(self):
        if not self._enabled:
            return

        frame = self._capture_frame()
        if frame is None:
            return

        # Encode as JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        success, jpeg_data = cv2.imencode('.jpg', frame, encode_params)
        if not success:
            return

        jpeg_bytes = jpeg_data.tobytes()

        # Store latest frame for MJPEG streaming
        with self._frame_lock:
            self._latest_frame = jpeg_bytes

        # Publish to ROS topic
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera'
        msg.format = 'jpeg'
        msg.data = jpeg_bytes
        self._pub.publish(msg)

    def _capture_frame(self) -> np.ndarray | None:
        if self._camera is not None:
            return self._camera.capture_array()

        # Test pattern fallback (no physical camera)
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        ts = time.strftime('%H:%M:%S')
        cv2.putText(frame, f'No Camera - {ts}', (50, self._height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        return frame

    def _enable_callback(self, msg: Bool):
        self._enabled = msg.data
        state = 'enabled' if self._enabled else 'disabled'
        self.get_logger().info(f'Camera streaming {state}')

    def get_latest_frame(self) -> bytes | None:
        """Get the latest JPEG frame (used by the FastAPI bridge for MJPEG streaming)."""
        with self._frame_lock:
            return self._latest_frame

    def destroy_node(self):
        if self._camera is not None:
            self._camera.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
