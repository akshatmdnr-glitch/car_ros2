"""
ROS 2 Motor Controller Node.

Subscribes to /cmd_vel (Twist messages) and drives motors via GPIO.
Supports L298N and similar H-bridge motor drivers connected to the
Raspberry Pi GPIO pins.

Publishes odometry-like feedback on /motor/status.
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String
import json
import time

# Try to import GPIO library
try:
    import lgpio
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False


class MotorControllerNode(Node):
    def __init__(self):
        super().__init__('motor_controller_node')

        # Parameters — GPIO pin assignments for L298N driver
        # Left motor: IN1=GPIO17, IN2=GPIO27, ENA=GPIO18
        # Right motor: IN3=GPIO22, IN4=GPIO5, ENB=GPIO19
        self.declare_parameter('left_forward_pin', 17)   # IN1
        self.declare_parameter('left_backward_pin', 27)  # IN2
        self.declare_parameter('left_pwm_pin', 18)       # ENA
        self.declare_parameter('right_forward_pin', 22)  # IN3
        self.declare_parameter('right_backward_pin', 5)  # IN4
        self.declare_parameter('right_pwm_pin', 19)      # ENB
        self.declare_parameter('max_speed', 1.0)  # m/s
        self.declare_parameter('wheel_base', 0.2)  # meters between wheels
        self.declare_parameter('status_rate', 5.0)  # Hz

        self._lf = self.get_parameter('left_forward_pin').value
        self._lb = self.get_parameter('left_backward_pin').value
        self._lp = self.get_parameter('left_pwm_pin').value
        self._rf = self.get_parameter('right_forward_pin').value
        self._rb = self.get_parameter('right_backward_pin').value
        self._rp = self.get_parameter('right_pwm_pin').value
        self._max_speed = self.get_parameter('max_speed').value
        self._wheel_base = self.get_parameter('wheel_base').value
        self._status_rate = self.get_parameter('status_rate').value

        # Velocity state
        self._linear = 0.0
        self._angular = 0.0
        self._last_cmd_time = time.time()

        # GPIO setup
        self._gpio_handle = None
        self._init_gpio()

        # Subscriber for velocity commands
        self._sub = self.create_subscription(Twist, 'cmd_vel', self._cmd_vel_callback, 10)

        # Publisher for motor status
        self._status_pub = self.create_publisher(String, 'motor/status', 10)

        # Timer for status publishing and safety timeout
        period = 1.0 / self._status_rate
        self._timer = self.create_timer(period, self._status_callback)

        self.get_logger().info('Motor controller node started')

    def _init_gpio(self):
        if not HAS_GPIO:
            self.get_logger().warn('lgpio not available — motor commands will be logged only')
            return

        try:
            self._gpio_handle = lgpio.gpiochip_open(0)
            for pin in [self._lf, self._lb, self._rf, self._rb]:
                lgpio.gpio_claim_output(self._gpio_handle, pin, 0)
            # PWM pins — start at 0% duty cycle, 1000 Hz
            for pin in [self._lp, self._rp]:
                lgpio.gpio_claim_output(self._gpio_handle, pin, 0)
            self.get_logger().info('GPIO initialized for motor control')
        except Exception as e:
            self.get_logger().error(f'GPIO init failed: {e}')
            self._gpio_handle = None

    def _cmd_vel_callback(self, msg: Twist):
        self._linear = msg.linear.x
        self._angular = msg.angular.z
        self._last_cmd_time = time.time()
        self._apply_motor_speeds()

    def _apply_motor_speeds(self):
        # Differential drive kinematics
        left_speed = self._linear - (self._angular * self._wheel_base / 2.0)
        right_speed = self._linear + (self._angular * self._wheel_base / 2.0)

        # Normalize to [-1, 1]
        left_duty = max(-1.0, min(1.0, left_speed / self._max_speed))
        right_duty = max(-1.0, min(1.0, right_speed / self._max_speed))

        self._set_motor('left', left_duty)
        self._set_motor('right', right_duty)

    def _set_motor(self, side: str, duty: float):
        if side == 'left':
            fwd_pin, bwd_pin, pwm_pin = self._lf, self._lb, self._lp
        else:
            fwd_pin, bwd_pin, pwm_pin = self._rf, self._rb, self._rp

        if self._gpio_handle is None:
            return

        try:
            if duty > 0:
                lgpio.gpio_write(self._gpio_handle, fwd_pin, 1)
                lgpio.gpio_write(self._gpio_handle, bwd_pin, 0)
            elif duty < 0:
                lgpio.gpio_write(self._gpio_handle, fwd_pin, 0)
                lgpio.gpio_write(self._gpio_handle, bwd_pin, 1)
            else:
                lgpio.gpio_write(self._gpio_handle, fwd_pin, 0)
                lgpio.gpio_write(self._gpio_handle, bwd_pin, 0)

            # Set PWM duty cycle (0-255 for lgpio)
            pwm_value = int(abs(duty) * 255)
            lgpio.tx_pwm(self._gpio_handle, pwm_pin, 1000, pwm_value / 255 * 100)
        except Exception as e:
            self.get_logger().error(f'Motor {side} error: {e}')

    def _status_callback(self):
        # Safety: stop motors if no command received for 500ms
        if time.time() - self._last_cmd_time > 0.5:
            if self._linear != 0.0 or self._angular != 0.0:
                self._linear = 0.0
                self._angular = 0.0
                self._apply_motor_speeds()
                self.get_logger().warn('Motor safety timeout — stopping motors')

        status = {
            'linear': self._linear,
            'angular': self._angular,
            'gpio_available': self._gpio_handle is not None,
            'timestamp': time.time(),
        }
        msg = String()
        msg.data = json.dumps(status)
        self._status_pub.publish(msg)

    def _stop_motors(self):
        self._linear = 0.0
        self._angular = 0.0
        self._apply_motor_speeds()

    def destroy_node(self):
        self._stop_motors()
        if self._gpio_handle is not None:
            lgpio.gpiochip_close(self._gpio_handle)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MotorControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
