"""Launch file for the car_slave system.

Launches all ROS 2 nodes:
  - camera_node
  - ultrasonic_sensor_node
  - motor_controller_node

Note: The FastAPI bridge (bridge.py) runs separately and manages
its own node lifecycle. Use `ros2 run car_slave bridge` to start
the full system with the HTTP API.

This launch file is for running nodes independently (e.g., for
testing or when using native ROS 2 communication instead of HTTP).
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # Launch arguments
    camera_fps = DeclareLaunchArgument('camera_fps', default_value='30')
    camera_width = DeclareLaunchArgument('camera_width', default_value='640')
    camera_height = DeclareLaunchArgument('camera_height', default_value='480')
    ultrasonic_rate = DeclareLaunchArgument('ultrasonic_rate', default_value='10.0')

    camera_node = Node(
        package='car_slave',
        executable='camera_node',
        name='camera_node',
        parameters=[{
            'fps': LaunchConfiguration('camera_fps'),
            'width': LaunchConfiguration('camera_width'),
            'height': LaunchConfiguration('camera_height'),
        }],
        output='screen',
    )

    uv_sensor_node = Node(
        package='car_slave',
        executable='ultrasonic_sensor_node',
        name='ultrasonic_sensor_node',
        parameters=[{
            'publish_rate': LaunchConfiguration('ultrasonic_rate'),
        }],
        output='screen',
    )

    motor_controller_node = Node(
        package='car_slave',
        executable='motor_controller_node',
        name='motor_controller_node',
        output='screen',
    )

    return LaunchDescription([
        camera_fps,
        camera_width,
        camera_height,
        ultrasonic_rate,
        camera_node,
        uv_sensor_node,
        motor_controller_node,
    ])
