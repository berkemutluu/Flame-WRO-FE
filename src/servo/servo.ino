#include <Servo.h>

Servo myServo;  // Create a Servo object

void setup() {
  myServo.attach(5);  // Attach the servo to pin 9
  myServo.write(125);   // Move to 0 degrees

}

void loop() {
  
}