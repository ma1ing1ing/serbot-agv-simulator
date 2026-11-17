"""I/O connection example only — no AI or game rules are implemented here.

Run from the repository root: python3 -m simulator.examples.camera_client
"""
from simulator.client import SimRobot

robot=SimRobot()
metadata=robot.camera_metadata()
print('가상 카메라:',metadata)
robot.camera_frame('artifacts/simulator/robot-camera.jpg')
print('카메라 JPEG 저장: artifacts/simulator/robot-camera.jpg')
print('MJPEG URL:',robot.camera_stream_url)
print('가상 초음파:',robot.ultrasonic())
print('가상 LiDAR:',len(robot.lidar_scan()['ranges']),'rays')
# Your AI can decode the JPEG, infer from it, and send commands:
# import cv2, numpy as np
# image=cv2.imdecode(np.frombuffer(robot.camera_frame(),np.uint8),cv2.IMREAD_COLOR)
# prediction=your_model(image)
# robot.command_velocity(linear_mps=0.1, angular_rps=0.0, seconds=0.3)
