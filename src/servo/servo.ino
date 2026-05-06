#include <Arduino.h>
#include <ServoTimer2.h>

const int servoPIN = 6;
ServoTimer2 steeringServo;

const int motorIN1 = 10;
const int motorIN2 = 9;

// servo : mg90s
// motor : jgb37-520
// motor driver : drv8874

// variables
int current_speed = 0;
int set_speed = 0;
unsigned long acc_time = 20;
unsigned long last_acc_time = 0;

// steering config
int middle = 90;
int degree_max = 165;
int degree_min = 15;
int current_degree = 0;
int set_degree = 0;

#define BUFFER_SIZE 64

char ringBuffer[BUFFER_SIZE];
int head = 0;
int tail = 0;

// --
void setup() {

  pinMode(motorIN1, OUTPUT);
  pinMode(motorIN2, OUTPUT);

  steeringServo.attach(servoPIN);

  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);

  Serial.begin(9600);
}

void loop() {

}

void steer(int angle) {
  angle = constrain(angle + middle, degree_min, degree_max);
  int pulseWidth = map(angle, degree_min, degree_max, 544, 2400);
  steeringServo.write(pulseWidth);
}

void drive(int speed) {
  if (speed == 0) {
    brake();
  } 
  else if (speed > 0) {
    moveForward(constrain(speed, 0, 255));
  } 
  else {
    moveBackward(constrain(abs(speed), 0, 255));
  }
}

void moveForward(int speed) {
  speed = constrain(speed, 0, 255);
  digitalWrite(motorIN1, LOW);
  analogWrite(motorIN2, speed);
}

void moveBackward(int speed) {
  speed = constrain(speed, 0, 255);
  analogWrite(motorIN1, speed);
  digitalWrite(motorIN2, LOW);
}

void coast() {

  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);
}

void brake() {
  digitalWrite(motorIN1, HIGH);
  digitalWrite(motorIN2, HIGH);

}