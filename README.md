# Car Slave — ROS 2 Raspberry Pi Robot Controller

ROS 2 Jazzy slave system that runs on the Raspberry Pi. Provides camera streaming, UV sensor readings, and motor control via ROS 2 nodes, with a FastAPI HTTP bridge for communication with the master dashboard.

## Architecture

```
[ Master (Ubuntu Dashboard) ]
        |
   HTTP Request (REST API)
        |
        v
[ FastAPI Server (Raspberry Pi :8000) ]
        |
   Publishes/Subscribes ROS 2 Topics
        |
        v
[ Camera Node | UV Sensor Node | Motor Controller Node ]
```

## ROS 2 Nodes

| Node | Topic | Type | Description |
|------|-------|------|-------------|
| `camera_node` | `/camera/image/compressed` | `sensor_msgs/CompressedImage` | Publishes JPEG frames from Pi Camera |
| `camera_node` | `/camera/enable` | `std_msgs/Bool` | Subscribe to enable/disable camera |
| `uv_sensor_node` | `/uv_sensor/reading` | `std_msgs/Float32` | Publishes UV index readings |
| `motor_controller_node` | `/cmd_vel` | `geometry_msgs/Twist` | Subscribes to velocity commands |
| `motor_controller_node` | `/motor/status` | `std_msgs/String` | Publishes motor status JSON |
| `gyro_sensor_node` | `/gyro/imu` | `sensor_msgs/Imu` | Publishes IMU data (accel + gyro) |
| `gyro_sensor_node` | `/gyro/status` | `std_msgs/String` | Publishes gyro status JSON |

## HTTP API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/status` | Full system status |
| `POST` | `/cmd_vel` | Send motor command `{"linear_x": 0.5, "angular_z": 0.0}` |
| `POST` | `/stop` | Emergency stop |
| `GET` | `/distance` | Latest ultrasonic distance reading (cm) |
| `GET` | `/gyro` | Latest gyroscope/IMU readings |
| `GET` | `/camera/stream` | MJPEG video stream (embed in `<img>` tag) |
| `GET` | `/camera/snapshot` | Single JPEG frame |
| `POST` | `/camera/enable` | Enable/disable camera `{"enabled": true}` |

## Setup

### Prerequisites

- Raspberry Pi with ROS 2 Jazzy (built from source at `~/ros2_jazzy/`)
- Pi Camera module (tested with `rpicam-hello --autofocus-mode=continuous`)
- Python 3.11+

### Install Dependencies

```bash
# Source ROS 2
source ~/ros2_jazzy/install/setup.bash

# Install Python dependencies
pip install fastapi uvicorn[standard] pydantic
```

### Build the Package

```bash
# From your colcon workspace (e.g., ~/ros2_ws/)
# Symlink or copy car_slave into src/
cd ~/ros2_ws
ln -s ~/car_slave src/car_slave

# Build
colcon build --packages-select car_slave --symlink-install
source install/setup.bash
```

## Running

### Full System (recommended)

Start all nodes + FastAPI bridge in one process:

```bash
source ~/ros2_jazzy/install/setup.bash
source ~/ros2_ws/install/setup.bash

# Option 1: via ros2 run
ros2 run car_slave bridge

# Option 2: via python directly
python3 main.py
```

The HTTP API will be available at `http://<pi-ip>:8000`.

To restrict the bridge to a specific network path, start it with one of these flags:

```bash
# Accept requests on any interface (default)
ros2 run car_slave bridge --network-mode any

# Ethernet only
ros2 run car_slave bridge --network-mode ethernet

# Wi-Fi only
ros2 run car_slave bridge --network-mode wifi
```

You can also override the preferred interface names when needed:

```bash
ros2 run car_slave bridge --network-mode ethernet --ethernet-iface enp1s0
ros2 run car_slave bridge --network-mode wifi --wifi-iface wlp2s0
```

### Individual Nodes (for testing)

```bash
# Launch all nodes without HTTP bridge
ros2 launch car_slave car_slave_launch.py

# Or run individually
ros2 run car_slave camera_node
ros2 run car_slave uv_sensor_node
ros2 run car_slave motor_controller_node
```

## Master Dashboard Usage

### Video Stream

Embed the MJPEG stream directly in HTML:

```html
<img src="http://<pi-ip>:8000/camera/stream" />
```

### Send Motor Commands

```bash
# Move forward
curl -X POST http://<pi-ip>:8000/cmd_vel \
  -H "Content-Type: application/json" \
  -d '{"linear_x": 0.5, "angular_z": 0.0}'

# Turn left
curl -X POST http://<pi-ip>:8000/cmd_vel \
  -H "Content-Type: application/json" \
  -d '{"linear_x": 0.0, "angular_z": 0.5}'

# Emergency stop
curl -X POST http://<pi-ip>:8000/stop
```

### Read UV Sensor

```bash
curl http://<pi-ip>:8000/uv
# {"uv_index": 5.3, "sensor_type": "veml6075", "timestamp": 1742900000.0}
```

## Configuration

Edit `config/default_params.yaml` for GPIO pins, camera resolution, sensor type, etc. Pass as a parameter file:

```bash
ros2 run car_slave bridge --ros-args --params-file config/default_params.yaml
```