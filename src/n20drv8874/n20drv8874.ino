const int encoderPinA = 3;
const int encoderPinB = 2;

volatile long encoderPos = 0;
volatile bool changed = false;

void setup() {
  Serial.begin(9600);
  
  // INPUT_PULLUP değil, çünkü Hall effect kendi sinyalini üretiyor
  pinMode(encoderPinA, INPUT);
  pinMode(encoderPinB, INPUT);
  
  attachInterrupt(digitalPinToInterrupt(encoderPinA), readEncoder, CHANGE);
  attachInterrupt(digitalPinToInterrupt(encoderPinB), readEncoder, CHANGE);
  
  Serial.println("Encoder test - motoru elinizle cevirin:");
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
  bool a = digitalRead(encoderPinA);
  bool b = digitalRead(encoderPinB);
  
  if (a == b) {
    encoderPos++;
  } else {
    encoderPos--;
  }
  changed = true;
}