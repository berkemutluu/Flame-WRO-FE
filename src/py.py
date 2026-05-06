import serial
import time


SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 9600

class ArduinoController:
    def __init__(self, port, baud_rate):
        self.ser = serial.Serial(port, baud_rate, timeout=1)
        time.sleep(2)  # Allow time for the Arduino to reset after serial connection

    def send_command(self, command):
        """Send a string command to the Arduino."""
        formatted_command = f"{command}\n"
        self.ser.write(formatted_command.encode('utf-8'))
        print(f"Sent: {formatted_command.strip()}")

    def steer(self, angle):
        """Send steering angle."""
        self.send_command(f"STEER:{angle}")

    def drive(self, speed):
        """Send drive speed."""
        self.send_command(f"DRIVE:{speed}")

    def close(self):
        self.ser.close()

if __name__ == '__main__':
    arduino = ArduinoController(SERIAL_PORT, BAUD_RATE)
    
    try:
        # Example usage:
        arduino.steer(10)   # Steer right
        time.sleep(1)
        arduino.drive(100)  # Move forward
        time.sleep(2)
        arduino.drive(0)    # Stop (brake)
        time.sleep(1)
        arduino.steer(0)    # Center steering
        
    finally:
        arduino.close()

  Serial.begin(9600);
}

void loop() {
  if (Serial.available() > 0) {
    // Read the incoming message until the newline character
    String incomingData = Serial.readStringUntil('\n');
    incomingData.trim(); // Remove any whitespace or carriage returns

    // Find the separator colon
    int separatorIndex = incomingData.indexOf(':');
    
    if (separatorIndex != -1) {
      // Split the string into command and value
      String command = incomingData.substring(0, separatorIndex);
      int value = incomingData.substring(separatorIndex + 1).toInt();

      // Execute based on the command
      if (command == "STEER") {
        steer(value);
      } 
      else if (command == "DRIVE") {
        drive(value);
      }
    }
  }
}


void steer(int angle)
{
  angle = angle + middle;
  
  if (angle > degree_max)
  {
    angle = degree_max;
  }
  else if (angle < degree_min)
  {
    angle = degree_min;
  }
  
  // Map the degree to microseconds since ServoTimer2 uses pulse width, not degrees
  int pulseWidth = map(angle, degree_min, degree_max, 544, 2400);
  steeringServo.write(pulseWidth);
}


void drive(int speed) {
  // Constrain speed to standard 8-bit PWM limits (-255 to 255)
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    // Move Forward
    analogWrite(motorIN1, speed);
    digitalWrite(motorIN2, LOW);
  } 
  else if (speed < 0) {
    // Move Backward
    digitalWrite(motorIN1, LOW);
    analogWrite(motorIN2, -speed); // Pass a positive value to analogWrite
  } 
  else {
    // Stop
    digitalWrite(motorIN1, LOW);
    digitalWrite(motorIN2, LOW);
  }
}