# WRO 2026: Future Engineers - Flame

Welcome to the official repository for Flame. This project documents the development of our autonomous vehicle designed to compete in the World Robot Olympiad (WRO) Future Engineers category.

**This robot is still a work in progress. Please keep in mind that this is only a preliminary report of what we have achieved up until the said time per entry.**

## Current Progress

As of 14th of May, we have finished the code of the open round. We have recorded a good amount of accuracy and the robot functions as expected. We have now moved on to the obstacle round.

Because of some compability issues between the clone arduino uno and raspberry pi, we have decided to change to an original arduino nano r4. The clone arduino ran at 16 mHz with 8-bit architecture compared with the new nano, 48mHz and 32-bit processor. This significantly solved our problems of latency between the wall detection and the steering+driving output. 

<img width="1200" height="1600" alt="WhatsApp Image 2026-05-09 at 12 30 58" src="https://github.com/user-attachments/assets/a729a93e-756a-40dd-9546-3b01f5968b09" />


We have released our wall tracking code on 7th of May. This code utilizes opencv to capture video and a "wall detection" algoritihm along with red and green obstacle detection capability. We have selected region of interests to crop the camera feed in half to avoid unwanted detections. The web interface of the pi uses flask to create a dashboard to see the live camera feed and to calibrate speed, colors and sensitivity. According to this the pi sends serial commands through the usb interface to the arduino, activating and driving the main motor and servo. The control logic uses a proportional_derivative codebase. Steering of the robot is proportional to the error of the robot.

On the 5th of May; we have put together our robots chassis with the electronics, sensor, motors, differential and steering systems. (We might reevaluate and possibly change these in the future.) We are currently working on the coding of our arduino board and pi's opencv modulation.

<img width="3024" height="4032" alt="image" src="https://github.com/user-attachments/assets/360d959e-3e3d-440a-b051-244e34ad4edb" />
<img width="4032" height="3024" alt="image" src="https://github.com/user-attachments/assets/d530215f-91bd-4308-92e7-e98b072b3036" />


As of April 28,we have designed and 3D printed our robot's chassis and integrated the motor into it. Additionally, we have developed a differantial and steering system optimized for reducing the turning radius of our robot.

<img width="4032" height="3024" alt="IMG_4815" src="https://github.com/user-attachments/assets/a8d141b2-ab2a-4be5-b52c-5dfeddb3111a" />
<img width="3024" height="4032" alt="IMG_4814" src="https://github.com/user-attachments/assets/29564b30-a651-49cd-a292-e895a5c39c30" />

![WhatsApp Image 2026-04-02 at 15 32 51 (2)](https://github.com/user-attachments/assets/a9bc148b-3fa8-4b7a-9b59-c28fcdd696c8)


## Project Overview
Our objective was to develop a small-scale autonomous vehicle capable of track navigation, obstacle avoidance, and traffic signal recognition through computer vision and an advanced control algorithm. 

## Features
Lane Detection: Real-time processing using OpenCV to identify track boundaries.

Obstacle Avoidance: Integration of ultrasonic sensors and camera depth perception to navigate around colored blocks.

PID Control: Smooth steering and speed regulation using Proportional-Integral-Derivative controllers and using the MPU6050 IMU.

Traffic Sign Recognition: Utilizing a trained model to identify the folowing basic traffic contol signals: "Turn Left", "Turn Right", "Move Forward", "Move Backward", "Stop" and "Go" signals.


## Bill of Materials (BOM)

<img width="975" height="722" alt="WRO Schematic" src="https://github.com/user-attachments/assets/486fa8f0-4040-46df-8224-3d5821d0667d" />



### 1. Computing & Control

Main Controller: Raspberry Pi 5 (8GB RAM)

Cooling: Raspberry Pi 5 Active Cooler + Aluminum Heatsink Set

Storage: SanDisk Extreme Pro 32GB MicroSD Card

Power Input: USB-C Power Cable with Integrated Switch (Type-C)

Display Interface: Micro HDMI to HDMI Cable (1.5m)

Second Controller: ~~Arduino Uno r3 (clone)~~ (For the drivetrain and sensors) Changed to a arduino nano r4 for latency issues.

### 2. Perception & Sensing

Primary Camera: Raspberry Pi Camera Module 3 (Wide Angle)

Camera Connection: Standard-to-Mini Camera Ribbon Cable (20cm)

Inertial Measurement: MPU6050 6-Axis Accelerometer and Gyroscope Sensor 

Object Detection: HC-SR04 Ultrasonic Distance Sensors (3 units)

Color Detection: TCS3200 Color Recognition Sensor Module

### 3. Propulsion & Drive System

Main Drive Motor: JGB37-520 DC Gear Motor (12V, 1590 RPM)

Secondary/Testing Motor: JGA12-520 DC Gear Motor (6V, 1500 RPM)

Motor Driver: DRV8874 Single Brushed DC Motor Driver Carrier

### 4. Power Management

Battery: 3300mAh 7.4V 2S Li-Po Battery (2 units)

Voltage Regulation (Step-Down): * XL4016 High-Power DC-DC Buck Converter (5A)

LM2596 DC-DC Buck Converter (3A)

Voltage Regulation (Step-Up): MT3608 Adjustable DC-DC Boost Converter (2 units)

Specialty Power: USB-C QC4.0/QC3.0 Fast Charging Module (6V-35V Input)

### 5. Wiring & Connectivity

Connectors: * XT60 Male Connection Cables (12AWG)

XT60 to Banana Plug Adapter Cable

DC Barrel Jack with Terminal Block

Wiring: * 14 AWG High-Flex Silicone Wire (Red and Black)

~~Rapid Wire Connection Kit (55 pieces)~~ We decided to ditch this in favor of soldering. These WAGO connectors really save time and effort when connecting components, but takes up a lot of space. Also, it was nearly impossible to tidy our wires with these connectores attached.

Management: Cable Tie/Zip Tie Set

### 6. Mechanical Hardware

Fasteners: * Assorted Screw and Nut Set (200 pieces)

M2 Screws and Nuts (8mm)

M4 Screws (6mm & 12mm), Washers, and Nuts

### 7. 3D-Printed Parts

Our robot has a total of 3 pieces which are 3d printed. Theses are:

the chassis, 

MG90s servo to lego adapter

and our JGB37-520 motor to lego adapter. 
Developing these parts took a lot of trial and error mainly because of tolerances. The printed parts did not expecatations, mainly because of durability reasons, but we have fixed this by increasing the infill rate of our adapters. This way we could combine the high-quality and durable lego parts with our motors.

<img width="4032" height="3024" alt="image" src="https://github.com/user-attachments/assets/241b9292-bb0e-4605-a3a8-7be53221bdcd" />
<img width="4032" height="3024" alt="image" src="https://github.com/user-attachments/assets/e8099160-08ab-4de4-947d-09be8c982bc4" />


## Software Architecture
The software is primarily written in Python, leveraging the following libraries:

OpenCV: For image processing, color masking, and Canny edge detection.

NumPy: For high-performance mathematical operations on image arrays.

ServoTimer2: For high-accuracy servo operations.

### Logic Flow

Perception: Capture frames and apply a perspective transform (Bird's-Eye View).

Processing: Filter colors (orange/blue lines) and calculate the deviation from the center.

Decision: The PID controller calculates the necessary steering angle based on the error.

Action: Pulse Width Modulation (PWM) signals are sent to the motors via DRV8874.

## Repository Structure
Plaintext
├── src/                # Core source code (Python scripts)

│   ├── main.py         # Entry point for the robot

│   ├── vision.py       # OpenCV lane and object detection

│   └── control.py      # PID and motor logic

├── models/             # Trained AI models for sign recognition

├── hardware/           # 3D models (STL) and circuit diagrams

├── docs/               # Engineering journals and photos

└── README.md

## Setup and Installation
To run the code locally for testing or on your robot:

Clone the repository:

Bash
git clone https://github.com/berkemutluu/flame-wro-fe.git
Install dependencies:

Bash
pip install opencv-python numpy servotimer2

Run the main application:

Bash
python src/main.py
## Engineering Journal

## Evolution of the Powertrain
Our development process involved significant iterations in both hardware and chassis design to meet the speed and torque requirements of the WRO track.

### Phase 1: The LEGO Prototype

<img width="1152" height="2048" alt="image" src="https://github.com/user-attachments/assets/b4bac3a6-0208-45d2-a44d-260d70b5efed" />

<img width="1536" height="2048" alt="image" src="https://github.com/user-attachments/assets/382b4c37-0c35-4aa0-9f4c-a3c25c82d3e3" />



https://github.com/user-attachments/assets/62a144ff-5d2f-4ce8-83bb-b0b5554a5f32




Chassis: Modified LEGO-based frame.

Motor: 6V N20 Micro Gear Motor.

Outcome: Unsuccessful. * Reasoning: While easy to prototype, the N20 motors lacked the necessary torque to move the chassis consistently at low speeds, and the top speed was insufficient for competitive lap times. The LEGO frame also exhibited too much flex under stress, affecting steering alignment.

### Phase 2: Custom High-Torque Build

Preliminary Circuit Version:

<img width="468" height="302" alt="circuit" src="https://github.com/user-attachments/assets/1e754c98-d8fd-4c4a-a1cb-7f15a5ce931d" />

Chassis: Custom 3D-printed rigid chassis for better weight distribution and sensor mounting.

Motor: JGB37-520 High-Torque DC Motor (Rated for 12V, 1590 RPM).

Power Solution: Due to weight and space constraints, we opted for a 7.4V LiPo battery instead of a bulkier 12V 3 cell source.

Outcome: Success.

Technical Detail: By running the 12V motors at 7.4V, we effectively operate at approximately 60–70% of the rated RPM. This trade-off was intentional: It provided a more manageable speed for our computer vision processing while maintaining significantly higher torque and structural stability compared to the N20/LEGO setup.

### Technical Challenges Overcome

PWM Calibration: We adjusted our Pulse Width Modulation (PWM) signals to account for the 7.4V limit, ensuring the PID controller had enough headroom to maintain constant speed during turns.

Voltage Sag: Documented the correlation between battery discharge and motor RPM, implementing a "battery compensation" factor in our motor control code.

Chassis Rigidity: The switch to a 3D-printed frame allowed for a lower center of gravity, reducing "body roll" which had previously caused camera feed instability.



## License
This project is licensed under the Apache 2.0 License - see the LICENSE file for details.
