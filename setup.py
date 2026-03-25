import os
from glob import glob
from setuptools import setup, find_packages

package_name = 'car_slave'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=[
        'setuptools',
        'fastapi',
        'uvicorn[standard]',
        'opencv-python',
        'pydantic',
    ],
    zip_safe=True,
    maintainer='moon',
    maintainer_email='todo@todo.com',
    description='ROS 2 slave system for robot car',
    license='MIT',
    entry_points={
        'console_scripts': [
            'camera_node = car_slave.nodes.camera_node:main',
            'ultrasonic_sensor_node = car_slave.nodes.uv_sensor_node:main',
            'motor_controller_node = car_slave.nodes.motor_controller_node:main',
            'bridge = car_slave.bridge:main',
        ],
    },
)
