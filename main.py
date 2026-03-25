"""
Car Slave — Convenience entry point.

Starts the full system: all ROS 2 nodes + FastAPI HTTP bridge.
Equivalent to: ros2 run car_slave bridge
"""

from car_slave.bridge import main

if __name__ == "__main__":
    main()
