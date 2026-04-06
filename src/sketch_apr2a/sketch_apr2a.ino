#include <ServoTimer2.h>

int enPin = 10;
int phPin = 11;
int encA = 2;
int encB = 3;
int servoPin = 6;

volatile long encoderCount = 0;
ServoTimer2 myServo;

void setup() {
  pinMode(enPin, OUTPUT);
  pinMode(phPin, OUTPUT);
  
  pinMode(encA, INPUT_PULLUP);
  pinMode(encB, INPUT_PULLUP);
  
  attachInterrupt(digitalPinToInterrupt(encA), readEncoder, RISING);
  
  myServo.attach(servoPin);
  drive(255);
}

void loop() {
}

void drive(int speed) {
  speed = constrain(speed, 0, 255);
  digitalWrite(phPin, HIGH);
  analogWrite(enPin, speed);
}

void stopMotor() {
  digitalWrite(enPin, LOW);
  digitalWrite(phPin, LOW);
}

void readEncoder() {
  if (digitalRead(encB) == HIGH) {
    encoderCount++;
  } else {
    encoderCount--;
  }
}

void setServoAngle(int angle) {
  angle = constrain(angle, 0, 180);
  int pulseWidth = map(angle, 0, 180, 750, 2250);
  myServo.write(pulseWidth);
}