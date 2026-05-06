#include <Arduino.h>
#include <ServoTimer2.h>

constexpr uint8_t SERVO_PIN = 6;
constexpr uint8_t MOTOR_IN1 = 10;
constexpr uint8_t MOTOR_IN2 = 9;

constexpr int SERVO_CENTER_DEG = 90;
constexpr int SERVO_MIN_DEG = 15;
constexpr int SERVO_MAX_DEG = 165;

constexpr int SERVO_PULSE_MIN = 544;
constexpr int SERVO_PULSE_MAX = 2400;

constexpr size_t LINE_BUF_SIZE = 48;

ServoTimer2 steeringServo;

char lineBuf[LINE_BUF_SIZE];
size_t lineLen = 0;

void stopMotor() {
  // True stop/coast for many drivers: both LOW
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, HIGH);
}

void driveMotor(int speed) {
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    analogWrite(MOTOR_IN1, speed);
    digitalWrite(MOTOR_IN2, LOW);
  } else if (speed < 0) {
    digitalWrite(MOTOR_IN1, LOW);
    analogWrite(MOTOR_IN2, -speed);
  } else {
    stopMotor();   // change to brakeMotor() if your driver needs braking instead
  }
}

void steer(int angle)
{
  angle = angle + SERVO_CENTER_DEG;
  
  if (angle > SERVO_MAX_DEG)
  {
    angle = SERVO_MAX_DEG;
  }
  else if (angle < SERVO_MIN_DEG)
  {
    angle = SERVO_MIN_DEG;
  }
  
  int pulseWidth = map(angle, SERVO_MIN_DEG, SERVO_MAX_DEG, 544, 2400);
  steeringServo.write(pulseWidth);
}

void handleCommand(char *cmd) {
  char *colon = strchr(cmd, ':');
  if (!colon) return;

  *colon = '\0';
  const char *name = cmd;
  int value = atoi(colon + 1);

  if (strcmp(name, "STEER") == 0) {
    steer(value);
  } else if (strcmp(name, "DRIVE") == 0) {
    driveMotor(value);
  } else if (strcmp(name, "STOP") == 0) {
    stopMotor();
  }
}

void setup() {
  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);

  steeringServo.attach(SERVO_PIN);
  stopMotor();

  Serial.begin(9600);
  Serial.setTimeout(20);
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      handleCommand(lineBuf);
      lineLen = 0;
    } else if (c != '\r') {
      if (lineLen < LINE_BUF_SIZE - 1) {
        lineBuf[lineLen++] = c;
      } else {
        lineLen = 0;
      }
    }
  }
}