"""
ROS 2 Ultrasonic Sensor Node (HC-SR04).

Measures distance using an HC-SR04 ultrasonic sensor connected to
the Raspberry Pi GPIO pins:
  TRIG → GPIO23
  ECHO → GPIO24
  VCC  → 5V
  GND  → GND

Publishes distance (in centimeters) to /ultrasonic/distance.
Falls back to simulated data if GPIO is not available.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
import time
import random

# Try to import GPIO library
try:
    import lgpio
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False


class UltrasonicSensorNode(Node):
    def __init__(self):
        super().__init__('ultrasonic_sensor_node')

        # Parameters
        self.declare_parameter('publish_rate', 10.0)  # Hz
        self.declare_parameter('trig_pin', 23)  # GPIO23
        self.declare_parameter('echo_pin', 24)  # GPIO24
        self.declare_parameter('max_distance', 400.0)  # cm — HC-SR04 max range
        self.declare_parameter('timeout_us', 30000)  # microseconds for echo timeout

        self._rate = self.get_parameter('publish_rate').value
        self._trig_pin = self.get_parameter('trig_pin').value
        self._echo_pin = self.get_parameter('echo_pin').value
        self._max_distance = self.get_parameter('max_distance').value
        self._timeout_us = self.get_parameter('timeout_us').value

        # Publisher
        self._pub = self.create_publisher(Float32, 'ultrasonic/distance', 10)

        # GPIO setup
        self._gpio_handle = None
        self._hw_available = self._init_gpio()

        # Timer
        period = 1.0 / self._rate
        self._timer = self.create_timer(period, self._read_callback)

        mode = "HC-SR04 on GPIO" if self._hw_available else "simulated"
        self.get_logger().info(
            f'Ultrasonic sensor node started ({mode}, '
            f'TRIG=GPIO{self._trig_pin}, ECHO=GPIO{self._echo_pin}, '
            f'rate={self._rate}Hz)'
        )

    def _init_gpio(self) -> bool:
        if not HAS_GPIO:
            self.get_logger().warn('lgpio not available — using simulated distance data')
            return False

        try:
            self._gpio_handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._gpio_handle, self._trig_pin, 0)
            lgpio.gpio_claim_input(self._gpio_handle, self._echo_pin)
            self.get_logger().info('GPIO initialized for HC-SR04')
            return True
        except Exception as e:
            self.get_logger().error(f'GPIO init failed: {e}')
            self._gpio_handle = None
            return False

    def _read_callback(self):
        distance = self._measure_distance()

        msg = Float32()
        msg.data = distance
        self._pub.publish(msg)

    def _measure_distance(self) -> float:
        """Measure distance in cm using HC-SR04 or return simulated value."""
        if not self._hw_available or self._gpio_handle is None:
            return self._simulated_distance()

        try:
            h = self._gpio_handle

            # Send 10us trigger pulse
            lgpio.gpio_write(h, self._trig_pin, 0)
            time.sleep(0.000002)
            lgpio.gpio_write(h, self._trig_pin, 1)
            time.sleep(0.00001)
            lgpio.gpio_write(h, self._trig_pin, 0)

            # Wait for echo to go HIGH (start of echo pulse)
            timeout_start = time.monotonic()
            while lgpio.gpio_read(h, self._echo_pin) == 0:
                pulse_start = time.monotonic()
                if pulse_start - timeout_start > self._timeout_us / 1_000_000:
                    return self._max_distance  # timeout → no object detected

            # Wait for echo to go LOW (end of echo pulse)
            while lgpio.gpio_read(h, self._echo_pin) == 1:
                pulse_end = time.monotonic()
                if pulse_end - pulse_start > self._timeout_us / 1_000_000:
                    return self._max_distance

            # Calculate distance: speed of sound = 34300 cm/s
            # distance = (time * 34300) / 2
            pulse_duration = pulse_end - pulse_start
            distance = (pulse_duration * 34300.0) / 2.0

            return min(round(distance, 1), self._max_distance)

        except Exception as e:
            self.get_logger().error(f'Measurement error: {e}')
            return -1.0

    def _simulated_distance(self) -> float:
        """Return a simulated distance reading for testing without hardware."""
        base = 50.0 + 30.0 * (0.5 + 0.5 * (time.time() % 10) / 10)
        noise = random.uniform(-2.0, 2.0)
        return round(max(2.0, min(self._max_distance, base + noise)), 1)

    @property
    def active_sensor_type(self) -> str:
        return "hc-sr04" if self._hw_available else "simulated"

    def destroy_node(self):
        if self._gpio_handle is not None:
            lgpio.gpiochip_close(self._gpio_handle)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = UltrasonicSensorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
