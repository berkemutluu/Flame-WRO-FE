#include <Arduino.h>
#include <Servo.h>

// Defaults match your original wiring.
constexpr uint8_t SERVO_PIN = 6;

// true:  two PWM H-bridge inputs, like the original sketch: IN1=10, IN2=9
// false: one PWM/enable pin plus two direction pins
constexpr bool USE_TWO_PWM_MOTOR_DRIVER = true;
constexpr bool USE_SOFTWARE_PWM_FOR_TWO_PWM_DRIVER = true;
constexpr uint8_t MOTOR_IN1_PIN = 10;
constexpr uint8_t MOTOR_IN2_PIN = 9;
constexpr uint8_t MOTOR_PWM_PIN = 11;

// Set this to true if you wired a physical enable switch to ENABLE_PIN.
constexpr bool USE_ENABLE_PIN = false;
constexpr uint8_t ENABLE_PIN = 7;

constexpr int SERVO_CENTER_DEG = 90;
constexpr int SERVO_MIN_DEG = 15;
constexpr int SERVO_MAX_DEG = 165;

constexpr int MOTOR_MAX_PWM = 200;
constexpr uint16_t MOTOR_RAMP_INTERVAL_MS = 20;
constexpr int MOTOR_RAMP_STEP = 2;
constexpr uint16_t SOFTWARE_PWM_PERIOD_US = 2000;
constexpr uint16_t COMMAND_TIMEOUT_MS = 1000;
constexpr size_t LINE_BUF_SIZE = 64;
constexpr bool PRINT_COMMAND_ACKS = false;

Servo steeringServo;

char lineBuf[LINE_BUF_SIZE];
size_t lineLen = 0;

int targetSpeed = 0;
int currentSpeed = 0;
int outputSpeed = 0;
int targetAngle = SERVO_CENTER_DEG;
unsigned long lastRampMs = 0;
unsigned long lastCommandMs = 0;

bool outputsEnabled() {
  return !USE_ENABLE_PIN || digitalRead(ENABLE_PIN) == HIGH;
}

int clampInt(int value, int lo, int hi) {
  return max(lo, min(hi, value));
}

void writeSteering(int absoluteAngleDeg) {
  targetAngle = clampInt(absoluteAngleDeg, SERVO_MIN_DEG, SERVO_MAX_DEG);
  steeringServo.write(targetAngle);
}

void writeMotorPwm(int speed) {
  speed = clampInt(speed, -MOTOR_MAX_PWM, MOTOR_MAX_PWM);
  if (!outputsEnabled()) {
    speed = 0;
  }

  if (USE_TWO_PWM_MOTOR_DRIVER) {
    if (USE_SOFTWARE_PWM_FOR_TWO_PWM_DRIVER) {
      outputSpeed = speed;
      if (speed == 0) {
        digitalWrite(MOTOR_IN1_PIN, LOW);
        digitalWrite(MOTOR_IN2_PIN, LOW);
      }
      return;
    }

    if (speed > 0) {
      analogWrite(MOTOR_IN1_PIN, speed);
      digitalWrite(MOTOR_IN2_PIN, LOW);
    } else if (speed < 0) {
      digitalWrite(MOTOR_IN1_PIN, LOW);
      analogWrite(MOTOR_IN2_PIN, -speed);
    } else {
      analogWrite(MOTOR_IN1_PIN, 0);
      analogWrite(MOTOR_IN2_PIN, 0);
      digitalWrite(MOTOR_IN1_PIN, LOW);
      digitalWrite(MOTOR_IN2_PIN, LOW);
    }
    return;
  }

  if (speed > 0) {
    digitalWrite(MOTOR_IN1_PIN, HIGH);
    digitalWrite(MOTOR_IN2_PIN, LOW);
  } else if (speed < 0) {
    digitalWrite(MOTOR_IN1_PIN, LOW);
    digitalWrite(MOTOR_IN2_PIN, HIGH);
  } else {
    digitalWrite(MOTOR_IN1_PIN, LOW);
    digitalWrite(MOTOR_IN2_PIN, LOW);
  }

  analogWrite(MOTOR_PWM_PIN, abs(speed));
}

void updateSoftwareMotorPwm() {
  if (!USE_TWO_PWM_MOTOR_DRIVER || !USE_SOFTWARE_PWM_FOR_TWO_PWM_DRIVER) {
    return;
  }

  int speed = clampInt(outputSpeed, -MOTOR_MAX_PWM, MOTOR_MAX_PWM);
  if (speed == 0) {
    digitalWrite(MOTOR_IN1_PIN, LOW);
    digitalWrite(MOTOR_IN2_PIN, LOW);
    return;
  }

  static unsigned long periodStartUs = micros();
  unsigned long nowUs = micros();
  unsigned long elapsed = nowUs - periodStartUs;
  if (elapsed >= SOFTWARE_PWM_PERIOD_US) {
    periodStartUs = nowUs;
    elapsed = 0;
  }

  unsigned int dutyUs = (static_cast<unsigned long>(abs(speed)) * SOFTWARE_PWM_PERIOD_US) / MOTOR_MAX_PWM;
  bool on = elapsed < dutyUs;
  if (speed > 0) {
    digitalWrite(MOTOR_IN1_PIN, on ? HIGH : LOW);
    digitalWrite(MOTOR_IN2_PIN, LOW);
  } else {
    digitalWrite(MOTOR_IN1_PIN, LOW);
    digitalWrite(MOTOR_IN2_PIN, on ? HIGH : LOW);
  }
}

void stopMotor() {
  targetSpeed = 0;
  currentSpeed = 0;
  writeMotorPwm(0);
}

void stopAll() {
  writeSteering(SERVO_CENTER_DEG);
  stopMotor();
}

void updateMotorRamp() {
  unsigned long now = millis();
  if (now - lastRampMs < MOTOR_RAMP_INTERVAL_MS) {
    return;
  }
  lastRampMs = now;

  if (currentSpeed < targetSpeed) {
    currentSpeed = min(currentSpeed + MOTOR_RAMP_STEP, targetSpeed);
  } else if (currentSpeed > targetSpeed) {
    currentSpeed = max(currentSpeed - MOTOR_RAMP_STEP, targetSpeed);
  }

  writeMotorPwm(currentSpeed);
}

bool parseIntStrict(const char *text, int &outValue) {
  char *endPtr = nullptr;
  long value = strtol(text, &endPtr, 10);
  if (text == endPtr) {
    return false;
  }
  while (*endPtr == ' ' || *endPtr == '\t') {
    endPtr++;
  }
  if (*endPtr != '\0') {
    return false;
  }
  outValue = static_cast<int>(value);
  return true;
}

void handleCommand(char *cmd) {
  char *colon = strchr(cmd, ':');
  if (colon) {
    *colon = '\0';
  }

  char *name = cmd;
  char *valueText = colon ? colon + 1 : nullptr;

  while (*name == ' ' || *name == '\t') {
    name++;
  }

  if (strcmp(name, "STOP") == 0) {
    stopAll();
    lastCommandMs = millis();
    if (PRINT_COMMAND_ACKS) {
      Serial.println("OK:STOP");
    }
    return;
  }

  if (!valueText) {
    Serial.println("ERR:VALUE");
    return;
  }

  int value = 0;
  if (!parseIntStrict(valueText, value)) {
    Serial.println("ERR:VALUE");
    return;
  }

  if (strcmp(name, "STEER") == 0) {
    writeSteering(value);
    lastCommandMs = millis();
    if (PRINT_COMMAND_ACKS) {
      Serial.println("OK:STEER");
    }
  } else if (strcmp(name, "DRIVE") == 0) {
    targetSpeed = clampInt(value, -MOTOR_MAX_PWM, MOTOR_MAX_PWM);
    lastCommandMs = millis();
    if (PRINT_COMMAND_ACKS) {
      Serial.println("OK:DRIVE");
    }
  } else {
    Serial.println("ERR:COMMAND");
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());

    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      handleCommand(lineBuf);
      lineLen = 0;
    } else if (c != '\r') {
      if (lineLen < LINE_BUF_SIZE - 1) {
        lineBuf[lineLen++] = c;
      } else {
        lineLen = 0;
        Serial.println("ERR:OVERFLOW");
      }
    }
  }
}

void setup() {
  pinMode(MOTOR_IN1_PIN, OUTPUT);
  pinMode(MOTOR_IN2_PIN, OUTPUT);
  if (!USE_TWO_PWM_MOTOR_DRIVER) {
    pinMode(MOTOR_PWM_PIN, OUTPUT);
  }
  if (USE_ENABLE_PIN) {
    pinMode(ENABLE_PIN, INPUT_PULLUP);
  }

  steeringServo.attach(SERVO_PIN);
  stopAll();

  Serial.begin(9600);
  delay(1500);
  lastCommandMs = millis();
  Serial.println("READY");
}

void loop() {
  readSerialCommands();

  if (millis() - lastCommandMs > COMMAND_TIMEOUT_MS) {
    targetSpeed = 0;
  }

  if (!outputsEnabled()) {
    targetSpeed = 0;
  }

  updateMotorRamp();
  updateSoftwareMotorPwm();
}
