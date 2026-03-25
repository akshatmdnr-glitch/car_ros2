"""
ROS 2 Gyro/IMU Sensor Node (MPU6050).

Reads gyroscope and accelerometer data from an MPU6050 IMU sensor
connected via I2C to the Raspberry Pi:
  VCC  → 3.3V or 5V
  GND  → GND
  SCL  → GPIO3 (SCL1)
  SDA  → GPIO2 (SDA1)

Publishes IMU data to /gyro/imu.
Falls back to simulated data if I2C is not available.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import String
import json
import time
import math
import random

try:
    from smbus2 import SMBus
    HAS_I2C = True
except ImportError:
    HAS_I2C = False


MPU6050_ADDR = 0x68
PWR_MGMT_1 = 0x6B
GYRO_XOUT_H = 0x43
ACCEL_XOUT_H = 0x3B


class GyroSensorNode(Node):
    def __init__(self):
        super().__init__('gyro_sensor_node')

        self.declare_parameter('publish_rate', 20.0)
        self.declare_parameter('i2c_bus', 1)
        self.declare_parameter('gyro_scale', 131.0)
        self.declare_parameter('accel_scale', 16384.0)
        self.declare_parameter('frame_id', 'imu_link')

        self._rate = self.get_parameter('publish_rate').value
        self._i2c_bus = self.get_parameter('i2c_bus').value
        self._gyro_scale = self.get_parameter('gyro_scale').value
        self._accel_scale = self.get_parameter('accel_scale').value
        self._frame_id = self.get_parameter('frame_id').value

        self._pub = self.create_publisher(Imu, 'gyro/imu', 10)
        self._status_pub = self.create_publisher(String, 'gyro/status', 10)

        self._bus = None
        self._hw_available = self._init_i2c()

        period = 1.0 / self._rate
        self._timer = self.create_timer(period, self._read_callback)

        self._last_time = time.time()

        mode = "MPU6050 on I2C" if self._hw_available else "simulated"
        self.get_logger().info(
            f'Gyro sensor node started ({mode}, rate={self._rate}Hz)'
        )

    def _init_i2c(self) -> bool:
        if not HAS_I2C:
            self.get_logger().warn('smbus2 not available — using simulated IMU data')
            return False

        try:
            self._bus = SMBus(self._i2c_bus)
            self._bus.write_byte_data(MPU6050_ADDR, PWR_MGMT_1, 0)
            self.get_logger().info(f'I2C initialized for MPU6050 at 0x{MPU6050_ADDR:02X}')
            return True
        except Exception as e:
            self.get_logger().error(f'I2C init failed: {e}')
            self._bus = None
            return False

    def _read_word(self, addr: int) -> int:
        high = self._bus.read_byte_data(MPU6050_ADDR, addr)
        low = self._bus.read_byte_data(MPU6050_ADDR, addr + 1)
        value = (high << 8) | low
        if value >= 0x8000:
            value -= 0x10000
        return value

    def _read_callback(self):
        current_time = time.time()
        dt = current_time - self._last_time
        self._last_time = current_time

        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._frame_id

        if self._hw_available and self._bus is not None:
            accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z = self._read_mpu6050()
        else:
            accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z = self._simulated_imu()

        msg.linear_acceleration.x = accel_x
        msg.linear_acceleration.y = accel_y
        msg.linear_acceleration.z = accel_z

        msg.angular_velocity.x = gyro_x
        msg.angular_velocity.y = gyro_y
        msg.angular_velocity.z = gyro_z

        for i in range(9):
            msg.orientation_covariance[i] = -1.0
            msg.linear_acceleration_covariance[i] = 0.0
            msg.angular_velocity_covariance[i] = 0.0
        msg.linear_acceleration_covariance[0] = 0.01
        msg.linear_acceleration_covariance[4] = 0.01
        msg.linear_acceleration_covariance[8] = 0.01
        msg.angular_velocity_covariance[0] = 0.001
        msg.angular_velocity_covariance[4] = 0.001
        msg.angular_velocity_covariance[8] = 0.001

        self._pub.publish(msg)
        self._publish_status(accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z)

    def _read_mpu6050(self) -> tuple:
        try:
            accel_x = self._read_word(ACCEL_XOUT_H) / self._accel_scale * 9.81
            accel_y = self._read_word(ACCEL_XOUT_H + 2) / self._accel_scale * 9.81
            accel_z = self._read_word(ACCEL_XOUT_H + 4) / self._accel_scale * 9.81

            gyro_x = math.radians(self._read_word(GYRO_XOUT_H) / self._gyro_scale)
            gyro_y = math.radians(self._read_word(GYRO_XOUT_H + 2) / self._gyro_scale)
            gyro_z = math.radians(self._read_word(GYRO_XOUT_H + 4) / self._gyro_scale)

            return accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z
        except Exception as e:
            self.get_logger().error(f'MPU6050 read error: {e}')
            return self._simulated_imu()

    def _simulated_imu(self) -> tuple:
        t = time.time()
        accel_x = 0.1 * math.sin(t * 0.5) + random.uniform(-0.05, 0.05)
        accel_y = 0.1 * math.cos(t * 0.5) + random.uniform(-0.05, 0.05)
        accel_z = 9.81 + random.uniform(-0.1, 0.1)

        gyro_x = math.radians(2.0 * math.sin(t * 0.3))
        gyro_y = math.radians(1.5 * math.cos(t * 0.4))
        gyro_z = math.radians(0.5 * math.sin(t * 0.2))

        return accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z

    def _publish_status(self, ax, ay, az, gx, gy, gz):
        status = {
            'accel': {'x': round(ax, 3), 'y': round(ay, 3), 'z': round(az, 3)},
            'gyro': {'x': round(math.degrees(gx), 2), 'y': round(math.degrees(gy), 2), 'z': round(math.degrees(gz), 2)},
            'sensor_type': 'mpu6050' if self._hw_available else 'simulated',
            'timestamp': time.time(),
        }
        msg = String()
        msg.data = json.dumps(status)
        self._status_pub.publish(msg)

    @property
    def active_sensor_type(self) -> str:
        return "mpu6050" if self._hw_available else "simulated"

    def destroy_node(self):
        if self._bus is not None:
            self._bus.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GyroSensorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()