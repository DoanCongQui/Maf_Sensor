#include <ModbusMaster.h>
#include <SoftwareSerial.h>

ModbusMaster node;
String rxLine; 

// Setup pin RX - TX 
SoftwareSerial rs485Serial(10, 11); // RX = 10, TX = 11

// RS485
const int RS485_DE = 9;
const int RS485_RE = 9;

// Sensor 1 
const int vgPin_1 = A0; 
float vgVoltage_1 = 0.0; 
float airFlow_1 = 0.0; // Luu luong khong khi (g/s)
int MAX_VALUE_1 = 120; // Thay doi gia tri max cua cam bien 

// Sensor 2
const int vgPin_2 = A1; 
float vgVoltage_2 = 0.0; 
float airFlow_2 = 0.0; // Luu luong khong khi (g/s)
int MAX_VALUE_2 = 120; // Thay doi gia tri max cua cam bien 

// Frequency control parameters
static const float SCALE = 166.6667f; // PWM 
static const int MAX_RPM = 3000;
int hzTarget = 0;
bool inverterRunning = false;
bool stopHold = false;
unsigned long lastAutoIncMs = 0;

// ------------------------- Modbus TX dir --------------------------------
void preTransmission() { digitalWrite(RS485_DE, HIGH); digitalWrite(RS485_RE, HIGH); }
void postTransmission(){ digitalWrite(RS485_DE, LOW);  digitalWrite(RS485_RE, LOW);  }

// Write frequency (Hz) down to the inverter
bool writeFreqHz(int hz) {
  if (hz < 0) hz = 0;
  if (hz > 60) hz = 60;
  uint16_t raw = (uint16_t) lroundf(hz * SCALE);
  uint8_t res = node.writeSingleRegister(0x2000, raw);
  if (res == node.ku8MBSuccess) {
    hzTarget = hz;
    return true;
  }
  return false;
}

// Send run command to inverter
bool cmdRun()  { return node.writeSingleRegister(0x1000, 0x0001) == node.ku8MBSuccess; } // RUN

// Send stop command to inverter
bool cmdStop() { 
  node.writeSingleRegister(0x2000, 0); // Reset to 0Hz and Off
  return node.writeSingleRegister(0x1000, 0x0005) == node.ku8MBSuccess; 
}

int hzToRpm(int hz) {
  return (hz * MAX_RPM) / 60;
}

void hzIncrease(int fHz, int secondsF){
  vgVoltage_1 = analogRead(vgPin_1) * (5.0 / 1023.0);
  vgVoltage_2 = analogRead(vgPin_2) * (5.0 / 1023.0);
  airFlow_1 = (vgVoltage_1 - 0.5) * (MAX_VALUE_1 / (4.5 - 0.5));
  airFlow_2 = (vgVoltage_2 - 0.5) * (MAX_VALUE_2 / (4.5 - 0.5));
  if (inverterRunning && !stopHold && (millis() - lastAutoIncMs >= secondsF)) {
    lastAutoIncMs = millis();
    if (hzTarget < 60) {
      writeFreqHz(hzTarget + fHz);
      Serial.print("OK AUTO_INC "); Serial.println(hzTarget);
    }
  }
}

// Display send status
void sendStatus() {
  int rpm = hzToRpm(hzTarget);
  Serial.print("STATUS hz=");   Serial.print(hzTarget);
  Serial.print(" rpm=");        Serial.print(rpm);
  Serial.print(" run=");        Serial.print(inverterRunning ? 1 : 0);
  Serial.print(" hold=");       Serial.print(stopHold ? 1 : 0);
  Serial.print(" flow1=");      Serial.print(airFlow_1);
  Serial.print(" volt1=");      Serial.print(vgVoltage_1);
  Serial.print(" flow2=");      Serial.print(airFlow_2);
  Serial.print(" volt2=");      Serial.println(vgVoltage_2);
}

// ======================= MAIN =========================
void setup() {
  pinMode(RS485_DE, OUTPUT);
  pinMode(RS485_RE, OUTPUT);
  pinMode(vgPin_1, INPUT);
  pinMode(vgPin_2, INPUT);
  digitalWrite(RS485_DE, LOW);
  digitalWrite(RS485_RE, LOW);

  Serial.begin(115200);  
  rs485Serial.begin(9600);

  node.begin(1, rs485Serial);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);

  // start frequency setup 0Hz
  writeFreqHz(0);
  inverterRunning = false;
  stopHold = false;
  lastAutoIncMs = millis();

  Serial.println("OK Arduino Ready (Modbus bridge).");
  sendStatus();
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      rxLine.trim();
      if (rxLine.length() > 0) {
        // Command process
        rxLine.toUpperCase();

        // ----  Command Run -------
        if (rxLine == "RUN") {
          if (cmdRun()) { inverterRunning = true; Serial.println("OK RUN"); }
          else Serial.println("ERR RUN_FAIL");

        } 
        
        // ----  Command Stop -------
        else if (rxLine == "STOP") {
          if (cmdStop()) { inverterRunning = false; writeFreqHz(0); Serial.println("OK STOP"); }
          else Serial.println("ERR STOP_FAIL");

        } 
        
        // ----  Command Set Hz -------
        else if (rxLine.startsWith("SET_HZ")) {
          int spaceIdx = rxLine.indexOf(' ');
          if (spaceIdx > 0) {
            int val = rxLine.substring(spaceIdx + 1).toInt();
            if (val < 0 || val > 60) {
              Serial.println("ERR HZ_RANGE(0..60)");
            } else {
              if (writeFreqHz(val)) Serial.println("OK SET_HZ");
              else Serial.println("ERR SET_FAIL");
            }
          } else {
            Serial.println("ERR ARG_REQUIRED");
          }

        } 
        
        // ----  Command Reset -------
        else if (rxLine == "RESET") {
          inverterRunning = false;
          if (writeFreqHz(0)) Serial.println("OK RESET");
          else Serial.println("ERR RESET_FAIL");

        } 
        
        // ----  Command Status -------
        else if (rxLine == "STATUS") {
          sendStatus();

        } 
        
        // ----  Command Hold Stop -------
        else if (rxLine.startsWith("HOLD_STOP")) {
          // HOLD_STOP ON|OFF
          int sp = rxLine.indexOf(' ');
          if (sp > 0) {
            String v = rxLine.substring(sp + 1);
            v.trim();
            if (v == "ON")  { stopHold = true;  Serial.println("OK HOLD_STOP ON"); }
            else if (v == "OFF") { stopHold = false; Serial.println("OK HOLD_STOP OFF"); }
            else Serial.println("ERR HOLD_ARG(ON|OFF)");
          } else {
            Serial.println("ERR ARG_REQUIRED");
          }

        } else {
          Serial.println("ERR UNKNOWN_CMD");
        }
      }
      rxLine = ""; // clear line 
    } else {
      rxLine += c;
      if (rxLine.length() > 100) rxLine = ""; 
    }
  }

  // Tang tang so 
  hzIncrease(1, 2000);
  
  
}
