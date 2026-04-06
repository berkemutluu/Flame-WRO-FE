// DRV8874 Motor Sürücü + Encoderli N20 Motor Kontrol
// PWM (IN/IN) Modu - PMODE = HIGH

// Motor Sürücü Pinleri
const int PIN_IN1 = 9;      // PWM pin
const int PIN_IN2 = 10;     // PWM pin
const int PIN_PMODE = 8;    // PMODE kontrolü (HIGH = PWM modu)
const int PIN_SLEEP = 7;    // SLEEP pin (HIGH = aktif)

// Encoder Pinleri
const int PIN_ENC_A = 2;    // Interrupt pin
const int PIN_ENC_B = 3;    // Interrupt pin

// Encoder değişkenleri
volatile long encoderPos = 0;
volatile int lastEncoded = 0;

// Motor parametreleri
int motorSpeed = 0;  // -255 ile +255 arası

void setup() {
  Serial.begin(115200);
  
  // Motor sürücü pinlerini ayarla
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_PMODE, OUTPUT);
  pinMode(PIN_SLEEP, OUTPUT);
  
  // PWM modunu aktif et
  digitalWrite(PIN_PMODE, HIGH);  // PWM (IN/IN) modu
  digitalWrite(PIN_SLEEP, HIGH);  // Sürücüyü aktif et
  
  // Encoder pinlerini ayarla
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  
  // Interrupt'ları ayarla
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), updateEncoder, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), updateEncoder, CHANGE);
  
  Serial.println("DRV8874 Motor Kontrol - PWM (IN/IN) Modu");
  Serial.println("Komutlar:");
  Serial.println("  +XXX : İleri hız (0-255)");
  Serial.println("  -XXX : Geri hız (0-255)");
  Serial.println("  s    : Dur");
  Serial.println("  b    : Fren");
  Serial.println("  r    : Encoder sıfırla");
}

void loop() {
  // Seri porttan komut oku
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command == "s") {
      // Durdur (coast - outputs off)
      stopMotor();
      Serial.println("Motor durduruldu (coast)");
    }
    else if (command == "b") {
      // Fren (brake - outputs shorted to ground)
      brakeMotor();
      Serial.println("Motor frenlendi");
    }
    else if (command == "r") {
      // Encoder sıfırla
      encoderPos = 0;
      Serial.println("Encoder sıfırlandı");
    }
    else {
      // Hız komutu
      int speed = command.toInt();
      if (speed >= -255 && speed <= 255) {
        setMotorSpeed(speed);
        Serial.print("Hız ayarlandı: ");
        Serial.println(speed);
      }
    }
  }
  
  // Encoder pozisyonunu göster (her 500ms'de bir)
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 500) {
    Serial.print("Encoder: ");
    Serial.print(encoderPos);
    Serial.print(" | Hız: ");
    Serial.println(motorSpeed);
    lastPrint = millis();
  }
}

// Motor hız kontrolü (-255 ile +255 arası)
void setMotorSpeed(int speed) {
  motorSpeed = constrain(speed, -255, 255);
  
  if (speed > 0) {
    // İleri hareket - forward/coast
    analogWrite(PIN_IN1, speed);    // PWM (H/Z)
    analogWrite(PIN_IN2, 0);        // LOW
  }
  else if (speed < 0) {
    // Geri hareket - reverse/coast
    analogWrite(PIN_IN1, 0);        // LOW
    analogWrite(PIN_IN2, -speed);   // PWM (L/Z)
  }
  else {
    // Durdur (coast)
    stopMotor();
  }
}

// Motor durdur (coast - yüksek empedans durumu)
void stopMotor() {
  analogWrite(PIN_IN1, 0);
  analogWrite(PIN_IN2, 0);
  motorSpeed = 0;
}

// Motor frenle (brake - çıkışlar ground'a kısa devre)
void brakeMotor() {
  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, HIGH);
  motorSpeed = 0;
}

// Encoder interrupt fonksiyonu
void updateEncoder() {
  int MSB = digitalRead(PIN_ENC_A);
  int LSB = digitalRead(PIN_ENC_B);
  
  int encoded = (MSB << 1) | LSB;
  int sum = (lastEncoded << 2) | encoded;
  
  if (sum == 0b1101 || sum == 0b0100 || sum == 0b0010 || sum == 0b1011) {
    encoderPos++;
  }
  else if (sum == 0b1110 || sum == 0b0111 || sum == 0b0001 || sum == 0b1000) {
    encoderPos--;
  }
  
  lastEncoded = encoded;
}