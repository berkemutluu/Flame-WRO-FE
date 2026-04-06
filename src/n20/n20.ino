// L298N Pinleri
const int IN1 = 13;
const int IN2 = 7;
const int ENA = 11; // Hız pinimiz

// Encoder Pinleri
const int encoderA = 2;
const int encoderB = 3;
volatile long encoderCount = 0;

void setup() {
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENA, OUTPUT);
  
  pinMode(encoderA, INPUT_PULLUP);
  pinMode(encoderB, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(encoderA), readEncoder, RISING);
  Serial.begin(9600);
}

void loop() {
  delay(1000);
  drive(1);

  delay(1000);
  drive(0.5);

  delay(1000);
  drive(0);
}

void drive(float throttle) {
  if (throttle > 0) {
    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, (int)(throttle * 255));
  } 
  else if (throttle < 0) {
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, HIGH);
    analogWrite(ENA, (int)(abs(throttle) * 255));
  } 
  else {
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, 0);
  }
}

void readEncoder() {
  if (digitalRead(encoderB) == HIGH) {
    encoderCount++;
  } else {
    encoderCount--;
  }
}