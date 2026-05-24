# Engineering Journal

**This Journal is out of date. Review README.md to see the current status.**

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
