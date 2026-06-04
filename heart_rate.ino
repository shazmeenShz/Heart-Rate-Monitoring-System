/*============================================================
 Project  : Heart Rate Monitoring System
 File     : Heart_Rate.ino
 Author   : Shazmeen Siddiqui
 Version  : 1.0
 ============================================================
 Purpose:
 Acquires pulse signals from the MAX30102 sensor,
 calculates heart rate (BPM), estimates blood
 pressure values, and displays the results on
 an OLED screen while transmitting data to a
 Python desktop GUI.

 Communication:
  I2C Address :
  - MAX30102 : 0x57
  - OLED SSD1306 : 0x3C

 Serial UART : 9600 baud
 
 WIRING:
   MAX30105  → VCC=3.3/5V, GND, SDA=A4, SCL=A5
   OLED SSD1306 (I2C 0x3C or 0x3D) → same SDA/SCL bus
   LED       → Pin 7  (220Ω resistor to GND)
   Buzzer    → Pin 8  (active buzzer)

 LIBRARIES NEEDED (install via Library Manager):
   • SparkFun MAX3010x Pulse and Proximity Sensor Library
   • Adafruit SSD1306
   • Adafruit GFX Library

 SERIAL MONITOR COMMANDS (9600 baud):
   L  → Force LOW BP state
   H  → Force HIGH BP state
   N  → Return to auto/normal mode
   I  → Run I2C scanner (lists all found addresses)

 BP RANGES:
   LOW BP    : Systolic < 90 mmHg
   NORMAL    : Systolic 90–139 mmHg
   HIGH BP   : Systolic ≥ 140 mmHg

   NOTE:
   The displayed blood pressure values are
   estimated from heart rate calculations and
   should not be considered clinical measurements.

   Last Updated:
    05 June 2026
 ============================================================
*/

#include <Wire.h>
#include "MAX30105.h"
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ── OLED ─────────────────────────────────────────────────────
#define SCREEN_W   128
#define SCREEN_H    64
#define OLED_RESET  -1
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, OLED_RESET);

// ── Sensor ───────────────────────────────────────────────────
MAX30105 particleSensor;

// ── GPIO ─────────────────────────────────────────────────────
#define LED_PIN    8
#define BUZZ_PIN   3

// ── Beat Detection ───────────────────────────────────────────
#define RATE_SIZE  8
byte  rates[RATE_SIZE];
byte  rateSpot     = 0;
long  lastBeat     = 0;
float bpm          = 0.0;
int   bpmAvg       = 0;

// ── Finger threshold ─────────────────────────────────────────
#define IR_FINGER_ON  50000UL

// ── BP values ────────────────────────────────────────────────
float sysBP  = 120.0;
float diaBP  =  80.0;
float spO2   =  98.0;

// ── Force mode (serial override) ─────────────────────────────
// 0=auto  1=force LOW  2=force HIGH
byte forceMode = 0;

// ── State machine ────────────────────────────────────────────
enum State { S_WELCOME, S_WAIT_FINGER, S_DETECTING, S_DATA };
State state = S_WELCOME;
unsigned long stateAt = 0;

// ── LED beat flash ────────────────────────────────────────────
unsigned long beatAt  = 0;
bool          flashing = false;

// ── EKG fake waveform ────────────────────────────────────────
#define WAVE_LEN  64
int8_t  waveBuf[WAVE_LEN];
byte    waveHead   = 0;
byte    ekgPhase   = 0;
unsigned long waveAt = 0;

// One EKG cycle (32 steps): flat → P-wave → QRS spike → T-wave → flat
const int8_t EKG[32] = {
  0,  0,  1,  2,  1,  0, -1, -2,
 -3, 20, 28, -8, -5, -2,  0,  1,
  3,  5,  4,  3,  2,  1,  0,  0,
  0,  0,  0,  0,  0,  0,  0,  0
};

// ── Beat detection internals ─────────────────────────────────
long  prevIR   = 0;
bool  goingUp  = false;
long  peakIR   = 0;
long  valleyIR = 999999;

// ── OLED address (auto-detected in setup) ────────────────────
uint8_t oledAddr = 0x3C;

// ════════════════════════════════════════════════════════════
//  I2C SCANNER UTILITY
// ════════════════════════════════════════════════════════════
void runI2CScanner() {
  Serial.println(F("--- I2C Scanner ---"));
  byte found = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte err = Wire.endTransmission();
    if (err == 0) {
      Serial.print(F("  Device at 0x"));
      if (addr < 16) Serial.print('0');
      Serial.print(addr, HEX);
      if (addr == 0x3C || addr == 0x3D) Serial.print(F("  ← likely OLED"));
      if (addr == 0x57)                  Serial.print(F("  ← likely MAX30105"));
      Serial.println();
      found++;
    }
  }
  if (found == 0) Serial.println(F("  No I2C devices found!"));
  Serial.println(F("-------------------"));
}

// ════════════════════════════════════════════════════════════
//  ERROR BLINK HELPERS
//  Halts execution with visible LED blink codes
// ════════════════════════════════════════════════════════════
void errorBlinkOLED() {
  // Slow single blink = OLED not found
  Serial.println(F("HALT: OLED not found. Blinking LED slowly."));
  while (1) {
    digitalWrite(LED_PIN, HIGH); delay(500);
    digitalWrite(LED_PIN, LOW);  delay(500);
  }
}

void errorBlinkSensor() {
  // Two fast blinks repeat = MAX30105 not found
  Serial.println(F("HALT: MAX30105 not found. Blinking LED twice fast."));
  while (1) {
    digitalWrite(LED_PIN, HIGH); delay(100);
    digitalWrite(LED_PIN, LOW);  delay(100);
    digitalWrite(LED_PIN, HIGH); delay(100);
    digitalWrite(LED_PIN, LOW);  delay(700);
  }
}

// ════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(9600);
  Serial.println(F("=== Heart Monitor Boot ==="));
  Serial.println(F("Cmds: L=LowBP  H=HighBP  N=Normal  I=I2CScan"));

  pinMode(LED_PIN,  OUTPUT);
  pinMode(BUZZ_PIN, OUTPUT);
  ledBuzzerOff();

  Wire.begin();

  // ── Run I2C scan at boot so address is visible in Serial Monitor ──
  runI2CScanner();

  // ── OLED: try 0x3C first, then fall back to 0x3D ──────────────────
  bool oledOK = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (!oledOK) {
    Serial.println(F("OLED not at 0x3C, trying 0x3D..."));
    oledOK = display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
    if (oledOK) {
      oledAddr = 0x3D;
      Serial.println(F("OLED found at 0x3D."));
    }
  } else {
    Serial.println(F("OLED found at 0x3C."));
  }

  if (!oledOK) {
    errorBlinkOLED();   // never returns
  }

  display.clearDisplay();
  display.display();
  Serial.println(F("OLED OK"));

  // ── MAX30105 ────────────────────────────────────────────────────────
  // Try standard I2C speed first; fall back if fast fails
  if (!particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println(F("MAX30105 not found at standard speed, trying fast..."));
    if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
      errorBlinkSensor();  // never returns
    }
  }
  Serial.println(F("MAX30105 OK"));

  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x1F);
  particleSensor.setPulseAmplitudeIR(0x1F);
  particleSensor.setPulseAmplitudeGreen(0);

  memset(waveBuf, 0, sizeof(waveBuf));
  memset(rates,   0, sizeof(rates));

  stateAt = millis();
  drawWelcome();
}

// ════════════════════════════════════════════════════════════
//  LOOP
// ════════════════════════════════════════════════════════════
void loop() {
  handleSerial();

  unsigned long now = millis();
  long irVal  = particleSensor.getIR();
  long redVal = particleSensor.getRed();
  bool finger = (irVal > IR_FINGER_ON);

  // ── Beat detection + LED/Buzzer pulse ────────────────────
  if (finger) {
    detectBeat(irVal, now);
  } else {
    resetBeatStats();
  }

  // Turn off flash after 80 ms
  if (flashing && (now - beatAt > 80)) {
    ledBuzzerOff();
    flashing = false;
  }

  // ── States ───────────────────────────────────────────────
  switch (state) {

    case S_WELCOME:
      if (now - stateAt >= 2800) {
        state   = S_WAIT_FINGER;
        stateAt = now;
        drawWaitFinger(now);
      }
      break;

    case S_WAIT_FINGER:
      if (now - stateAt >= 700) {
        stateAt = now;
        drawWaitFinger(now);
      }
      if (finger) {
        state    = S_DETECTING;
        stateAt  = now;
        ekgPhase = 0;
        waveHead = 0;
        memset(waveBuf, 0, sizeof(waveBuf));
      }
      break;

    case S_DETECTING:
      if (!finger) {
        state   = S_WAIT_FINGER;
        stateAt = now;
        drawWaitFinger(now);
        break;
      }
      if (now - waveAt >= 55) {
        waveAt = now;
        pushEKG();
        drawDetecting(now);
      }
      // Move to data after 3.5 s (or 6 s timeout)
      if ((now - stateAt >= 3500 && bpmAvg > 0) || (now - stateAt >= 6000)) {
        if (bpmAvg == 0) bpmAvg = 72;   // fallback if no beat found
        estimateBP(irVal, redVal);
        state   = S_DATA;
        stateAt = now;
        drawData();
      }
      break;

    case S_DATA:
      if (now - stateAt >= 500) {
        stateAt = now;
        if (finger || forceMode) {
          if (finger) estimateBP(irVal, redVal);
          drawData();
        } else {
          // Finger removed, reset and go back
          delay(5000);

          bpmAvg   = 0;
          rateSpot = 0;
          memset(rates, 0, sizeof(rates));
          state   = S_WAIT_FINGER;
          stateAt = millis();
          drawWaitFinger(stateAt);
        }
      }
      break;
  }
}

// ════════════════════════════════════════════════════════════
//  BEAT DETECTION
// ════════════════════════════════════════════════════════════
void detectBeat(long ir, unsigned long now) {
  if (ir > prevIR) {
    goingUp = true;
    if (ir > peakIR) peakIR = ir;
  } else if (goingUp && ir < prevIR) {
    goingUp = false;
    long swing = peakIR - valleyIR;
    if (swing > 2500 && (now - lastBeat) > 400) {
      long interval = now - lastBeat;
      lastBeat = now;
      bpm = 60000.0 / (float)interval;
      if (bpm > 40 && bpm < 200) {
        rates[rateSpot % RATE_SIZE] = (byte)bpm;
        rateSpot++;
        bpmAvg = 0;
        for (byte i = 0; i < RATE_SIZE; i++) bpmAvg += rates[i];
        bpmAvg /= RATE_SIZE;
      }
      // Flash LED + beep
      digitalWrite(LED_PIN,  HIGH);
      digitalWrite(BUZZ_PIN, HIGH);
      beatAt   = now;
      flashing = true;
    }
    valleyIR = ir;
    peakIR   = ir;
  }
  if (ir < valleyIR) valleyIR = ir;
  prevIR = ir;
}

void resetBeatStats() {
  bpm      = 0;
  bpmAvg   = 0;
  rateSpot = 0;
  peakIR   = 0;
  valleyIR = 999999;
  goingUp  = false;
  ledBuzzerOff();
  flashing = false;
}

void ledBuzzerOff() {
  digitalWrite(LED_PIN,  LOW);
  digitalWrite(BUZZ_PIN, LOW);
}

// ════════════════════════════════════════════════════════════
//  BP ESTIMATION  (demo-grade, not clinical)
// ════════════════════════════════════════════════════════════
void estimateBP(long ir, long red) {
  if (forceMode == 1) { sysBP =  78; diaBP = 52; return; }
  if (forceMode == 2) { sysBP = 158; diaBP = 98; return; }
  if (ir == 0 || red == 0) return;

  float ratio = (float)red / (float)ir;
  spO2 = constrain(110.0 - 25.0 * ratio, 85.0, 100.0);

  float hrF = (bpmAvg > 0) ? ((float)bpmAvg - 60.0) / 40.0 : 0.5;
  hrF = constrain(hrF, 0.0, 1.5);

  sysBP = constrain(110.0 + hrF * 15.0 + (100.0 - spO2) * 1.0, 90.0, 140.0);
  diaBP = constrain(sysBP * 0.70, 60.0, 90.0);
}

// ════════════════════════════════════════════════════════════
//  SERIAL COMMANDS
// ════════════════════════════════════════════════════════════
void handleSerial() {
  while (Serial.available()) {
    char c = toupper(Serial.read());
    if (c == 'L') { forceMode = 1; state = S_DATA; drawData(); Serial.println(F(">> LOW BP forced")); }
    if (c == 'H') { forceMode = 2; state = S_DATA; drawData(); Serial.println(F(">> HIGH BP forced")); }
    if (c == 'N') { forceMode = 0;                             Serial.println(F(">> Auto mode")); }
    if (c == 'I') { runI2CScanner(); }
  }
}

// ════════════════════════════════════════════════════════════
//  EKG WAVEFORM
// ════════════════════════════════════════════════════════════
void pushEKG() {
  waveBuf[waveHead % WAVE_LEN] = EKG[ekgPhase % 32];
  waveHead++;
  ekgPhase++;
}

// ════════════════════════════════════════════════════════════
//  SCREEN 1 — WELCOME
// ════════════════════════════════════════════════════════════
void drawWelcome() {
  display.clearDisplay();

  drawHeart(56, 6, 1);

  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);

  display.setCursor(10, 26);
  display.print(F("Heart Rate Monitoring"));

  display.drawLine(0, 36, 127, 36, SSD1306_WHITE);

  display.setCursor(18, 40);
  display.print(F("& BP Estimator v1.1"));

  display.setCursor(24, 52);
  display.print(F("MAX30105 Sensor"));

  display.display();
}

// ════════════════════════════════════════════════════════════
//  SCREEN 2 — PLACE FINGER
// ════════════════════════════════════════════════════════════
byte dotAnim = 0;

void drawWaitFinger(unsigned long now) {
  dotAnim = (dotAnim + 1) % 4;

  display.clearDisplay();

  int bounce = (millis() / 300) % 2;
  drawHeart(55, 4 + bounce, 0);

  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(10, 28);
  display.print(F("Please place your"));
  display.setCursor(16, 39);
  display.print(F("finger on sensor"));

  display.setCursor(50, 54);
  for (byte i = 0; i < dotAnim; i++) display.print('.');

  display.display();
}

// ════════════════════════════════════════════════════════════
//  SCREEN 3 — DETECTING (scrolling EKG)
// ════════════════════════════════════════════════════════════
void drawDetecting(unsigned long now) {
  display.clearDisplay();

  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(14, 1);
  display.print(F("Detecting Heartbeat"));
  display.drawLine(0, 11, 127, 11, SSD1306_WHITE);

  // Draw scrolling EKG trace
  int baseY = 38;
  for (byte i = 0; i < WAVE_LEN - 1; i++) {
    int y0 = baseY - (int)waveBuf[(waveHead + i)     % WAVE_LEN];
    int y1 = baseY - (int)waveBuf[(waveHead + i + 1) % WAVE_LEN];
    // Clamp to display bounds
    y0 = constrain(y0, 12, 63);
    y1 = constrain(y1, 12, 63);
    display.drawLine(i * 2, y0, i * 2 + 1, y1, SSD1306_WHITE);
  }

  // Show live BPM during detection if available
  if (bpmAvg > 0) {
    display.setCursor(0, 55);
    display.print(F("HR: "));
    display.print(bpmAvg);
    display.print(F(" BPM"));
  } else if ((now / 450) % 2 == 0) {
    display.setCursor(30, 55);
    display.print(F("Analysing..."));
  }

  display.display();
}

// ════════════════════════════════════════════════════════════
//  SCREEN 4 — DATA  (3 BP states)
// ════════════════════════════════════════════════════════════
void drawData() {
  display.clearDisplay();

  bool lowBP  = (sysBP < 90.0);
  bool highBP = (sysBP >= 140.0);

  // ── Status banner ────────────────────────────────────────
  if (lowBP) {
    display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(4, 3);
    display.print(F("!  LOW BLOOD PRESSURE !"));
  } else if (highBP) {
    display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(2, 3);
    display.print(F("! HIGH BLOOD PRESSURE !"));
  } else {
    display.drawRect(0, 0, 128, 13, SSD1306_WHITE);
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(24, 3);
    display.print(F("BP  NORMAL  "));
    display.drawLine(106,  7, 109, 11, SSD1306_WHITE);
    display.drawLine(109, 11, 116,  4, SSD1306_WHITE);
  }

  display.setTextColor(SSD1306_WHITE);

  // ── Heart Rate (left column) ──────────────────────────────
  drawHeart(2, 15, 0);
  display.setTextSize(2);
  display.setCursor(22, 14);
  if (bpmAvg > 0) display.print(bpmAvg);
  else             display.print(F("--"));
  display.setTextSize(1);
  display.setCursor(56, 20);
  display.print(F("BPM"));

  // ── Divider ───────────────────────────────────────────────
  display.drawLine(0, 32, 127, 32, SSD1306_WHITE);

  // ── Systolic ─────────────────────────────────────────────
  display.setTextSize(1);
  display.setCursor(0, 35);
  display.print(F("SYS"));
  display.setTextSize(2);
  display.setCursor(26, 33);
  display.print((int)sysBP);
  display.setTextSize(1);
  display.setCursor(60, 35);
  display.print(F("mmHg"));

  // ── Diastolic ────────────────────────────────────────────
  display.setTextSize(1);
  display.setCursor(0, 51);
  display.print(F("DIA"));
  display.setTextSize(2);
  display.setCursor(26, 49);
  display.print((int)diaBP);
  display.setTextSize(1);
  display.setCursor(60, 51);
  display.print(F("mmHg"));

  // ── Arrow indicator (right side) ─────────────────────────
  if (lowBP) {
    // Down arrow
    display.drawLine(115, 36, 115, 56, SSD1306_WHITE);
    display.drawLine(110, 51, 115, 57, SSD1306_WHITE);
    display.drawLine(120, 51, 115, 57, SSD1306_WHITE);
  } else if (highBP) {
    // Up arrow
    display.drawLine(115, 56, 115, 36, SSD1306_WHITE);
    display.drawLine(110, 41, 115, 35, SSD1306_WHITE);
    display.drawLine(120, 41, 115, 35, SSD1306_WHITE);
  } else {
    // Equals / stable
    display.drawLine(108, 43, 124, 43, SSD1306_WHITE);
    display.drawLine(108, 49, 124, 49, SSD1306_WHITE);
  }

  display.display();

  // ── Serial log ───────────────────────────────────────────
  Serial.print(F("HR="));    Serial.print(bpmAvg);
  Serial.print(F(" SYS="));  Serial.print((int)sysBP);
  Serial.print(F(" DIA="));  Serial.print((int)diaBP);
  Serial.print(F(" SpO2=")); Serial.print((int)spO2);
  Serial.print(F("% | "));
  if (lowBP)       Serial.println(F("LOW BP"));
  else if (highBP) Serial.println(F("HIGH BP"));
  else             Serial.println(F("NORMAL BP"));
}

// ════════════════════════════════════════════════════════════
//  HEART DRAW HELPER  (primitive-based, no bitmap)
//  cx,cy = top-left of bounding box
//  sz: 0 = small (14x12),  1 = large (18x16)
// ════════════════════════════════════════════════════════════
void drawHeart(int cx, int cy, byte sz) {
  if (sz == 0) {
    display.fillCircle(cx + 4,  cy + 4, 3, SSD1306_WHITE);
    display.fillCircle(cx + 9,  cy + 4, 3, SSD1306_WHITE);
    display.fillTriangle(cx, cy + 5, cx + 13, cy + 5, cx + 6, cy + 12, SSD1306_WHITE);
  } else {
    display.fillCircle(cx + 5,  cy + 5, 4, SSD1306_WHITE);
    display.fillCircle(cx + 12, cy + 5, 4, SSD1306_WHITE);
    display.fillTriangle(cx, cy + 7, cx + 17, cy + 7, cx + 8, cy + 17, SSD1306_WHITE);
  }
}

