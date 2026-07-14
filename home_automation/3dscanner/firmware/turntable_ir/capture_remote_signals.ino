/*
 * Guided IR capture — turntable remote (14 buttons)
 * Library: IRremote v4.x (Armin Joachimsmeyer)  |  Board: Arduino Uno
 *
 * Wiring:  KY-022  S -> D2 (change IR_RECEIVE_PIN if you wired D3),  middle -> 5V,  "-" -> GND
 * Serial Monitor baud: 115200   (set the dropdown, or you'll see nothing)
 *
 * How it works:
 *   - It names each button and asks you to TAP it 3 times.
 *   - 3 taps are compared; a value must appear at least twice to be accepted
 *     (this rejects the occasional misread automatically).
 *   - Type  s <Enter>  to skip a button,  r <Enter>  to redo the current one.
 *   - At the end it prints a JSON block between clear markers. Copy everything
 *     between ===BEGIN...=== and ===END...=== into turntable_codes.json.
 *   - Send any character afterwards to run the whole capture again.
 *
 * NOTE: this only CAPTURES (KY-022 is receive-only). Replaying needs the IR LED.
 */

#include <IRremote.hpp>

#define IR_RECEIVE_PIN 2        // <-- set to the pin you got working (2 or 3)
#define SAMPLES        3        // taps per button (voting needs 3; keep at 3)

struct Button { const char* key; const char* label; };

// Order follows the remote top-to-bottom for easy following.
const Button BUTTONS[] = {
  {"POWER",              "On/Off (top-left square)"},
  {"ROTATE_CONTINUOUS",  "Continuous rotation (solid circle-arrow)"},
  {"ROTATE_INTERMITTENT","Intermittent rotation (dashed, 120deg/3s pause)"},
  {"SPEED_UP",           "Speed +  (accelerate)"},
  {"SPEED_DOWN",         "Speed -  (decelerate)"},
  {"CW",                 "Rotate clockwise (left arrow on ring)"},
  {"CCW",                "Rotate counter-clockwise (right arrow on ring)"},
  {"START_PAUSE",        "Start / Pause (center play-stop)"},
  {"ANGLE_45",           "Angle 45 (left of angle bar)"},
  {"ANGLE_90",           "Angle 90 (middle of angle bar)"},
  {"ANGLE_180",          "Angle 180 (right of angle bar)"},
  {"SET_HOME",           "Set origin (down-arrow to circle)"},
  {"RETURN_HOME",        "Return to origin (loop to circle)"},
  {"STEP_90",            "Step 90 auto-stop  ((1))"},
};
const uint8_t NUM_BUTTONS = sizeof(BUTTONS) / sizeof(BUTTONS[0]);

struct Capture {
  bool          captured;
  bool          skipped;
  decode_type_t protocol;
  uint16_t      address;
  uint16_t      command;
  uint32_t      rawData;
  uint8_t       bits;
};
Capture results[NUM_BUTTONS];

enum WaitResult { RES_GOT, RES_TIMEOUT, RES_SKIP, RES_REDO };

const char* protoName(decode_type_t p) {
  switch (p) {
    case UNKNOWN:   return "UNKNOWN";
    case NEC:       return "NEC";
    case NEC2:      return "NEC2";
    case ONKYO:     return "ONKYO";
    case APPLE:     return "APPLE";
    case PANASONIC: return "PANASONIC";
    case DENON:     return "DENON";
    case SHARP:     return "SHARP";
    case JVC:       return "JVC";
    case SONY:      return "SONY";
    case SAMSUNG:   return "SAMSUNG";
    case LG:        return "LG";
    case RC5:       return "RC5";
    case RC6:       return "RC6";
    default:        return "OTHER";
  }
}

bool equalCap(const Capture& a, const Capture& b) {
  return a.protocol == b.protocol && a.address == b.address &&
         a.command == b.command && a.rawData == b.rawData;
}

void printCapture(const Capture& c) {
  Serial.print(F("proto=")); Serial.print(protoName(c.protocol));
  Serial.print(F(" addr=0x")); Serial.print(c.address, HEX);
  Serial.print(F(" cmd=0x"));  Serial.print(c.command, HEX);
  Serial.print(F(" raw=0x"));  Serial.print(c.rawData, HEX);
  Serial.print(F(" bits="));   Serial.print(c.bits);
}

// Wait for one genuine (non-repeat) button frame, or a control key / timeout.
WaitResult waitForPress(Capture& out, unsigned long timeoutMs) {
  unsigned long start = millis();
  while (millis() - start < timeoutMs) {
    if (Serial.available()) {
      char ch = Serial.read();
      if (ch == 's' || ch == 'S') return RES_SKIP;
      if (ch == 'r' || ch == 'R') return RES_REDO;
    }
    if (IrReceiver.decode()) {
      bool isRepeat = IrReceiver.decodedIRData.flags &
                      (IRDATA_FLAGS_IS_REPEAT | IRDATA_FLAGS_IS_AUTO_REPEAT);
      if (!isRepeat) {
        out.protocol = IrReceiver.decodedIRData.protocol;
        out.address  = IrReceiver.decodedIRData.address;
        out.command  = IrReceiver.decodedIRData.command;
        out.rawData  = IrReceiver.decodedIRData.decodedRawData;
        out.bits     = IrReceiver.decodedIRData.numberOfBits;
        IrReceiver.resume();
        // Flush trailing frames for 500ms so one physical tap = one sample.
        unsigned long f = millis();
        while (millis() - f < 500) {
          if (IrReceiver.decode()) IrReceiver.resume();
        }
        return RES_GOT;
      }
      IrReceiver.resume();
    }
  }
  return RES_TIMEOUT;
}

void captureButton(uint8_t idx) {
  while (true) {                                   // loop enables redo
    Serial.println();
    Serial.print(F(">>> Button ")); Serial.print(idx + 1);
    Serial.print(F("/")); Serial.print(NUM_BUTTONS);
    Serial.print(F(":  ")); Serial.print(BUTTONS[idx].key);
    Serial.print(F("   (")); Serial.print(BUTTONS[idx].label); Serial.println(F(")"));
    Serial.print(F("    Tap it ")); Serial.print(SAMPLES);
    Serial.println(F(" times.   [s]=skip  [r]=redo"));

    Capture s[SAMPLES];
    bool restart = false;

    for (uint8_t i = 0; i < SAMPLES; i++) {
      WaitResult r = waitForPress(s[i], (i == 0) ? 40000UL : 20000UL);
      if (r == RES_SKIP) {
        results[idx].captured = false; results[idx].skipped = true;
        Serial.println(F("    -> SKIPPED")); return;
      }
      if (r == RES_REDO) { Serial.println(F("    -> redo")); restart = true; break; }
      if (r == RES_TIMEOUT) {
        if (i == 0) {
          results[idx].captured = false; results[idx].skipped = true;
          Serial.println(F("    (no input; SKIPPED)")); return;
        }
        Serial.println(F("    timeout -> redoing this button")); restart = true; break;
      }
      Serial.print(F("    tap ")); Serial.print(i + 1); Serial.print(F("/"));
      Serial.print(SAMPLES); Serial.print(F(": ")); printCapture(s[i]); Serial.println();
    }
    if (restart) continue;

    // Majority vote across 3 samples: a value must appear at least twice.
    Capture* winner = nullptr;
    bool unanimous = false;
    if (equalCap(s[0], s[1])) { winner = &s[0]; unanimous = equalCap(s[0], s[2]); }
    else if (equalCap(s[0], s[2])) { winner = &s[0]; }
    else if (equalCap(s[1], s[2])) { winner = &s[1]; }

    if (!winner) {
      Serial.println(F("    !! all three taps disagree - tap cleaner, retrying"));
      continue;
    }
    if (winner->protocol == UNKNOWN) {
      Serial.println(F("    note: UNKNOWN protocol - recorded, but replay may need sendRaw"));
    }
    results[idx] = *winner;
    results[idx].captured = true; results[idx].skipped = false;
    Serial.print(unanimous ? F("    [OK 3/3] ") : F("    [OK 2/3] "));
    printCapture(results[idx]); Serial.println();
    return;
  }
}

void printConfigJSON() {
  Serial.println();
  Serial.println(F("===BEGIN TURNTABLE IR CONFIG (JSON)==="));
  Serial.println(F("{"));
  Serial.println(F("  \"remote\": \"turntable\","));
  Serial.println(F("  \"library\": \"IRremote\","));
  Serial.println(F("  \"buttons\": {"));
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    Serial.print(F("    \"")); Serial.print(BUTTONS[i].key); Serial.print(F("\": "));
    if (!results[i].captured) {
      Serial.print(F("{\"skipped\": true}"));
    } else {
      Serial.print(F("{\"protocol\": \"")); Serial.print(protoName(results[i].protocol));
      Serial.print(F("\", \"address\": ")); Serial.print(results[i].address);
      Serial.print(F(", \"command\": "));   Serial.print(results[i].command);
      Serial.print(F(", \"raw\": "));        Serial.print(results[i].rawData);
      Serial.print(F(", \"bits\": "));       Serial.print(results[i].bits);
      Serial.print(F("}"));
    }
    if (i < NUM_BUTTONS - 1) Serial.print(F(","));
    Serial.println();
  }
  Serial.println(F("  }"));
  Serial.println(F("}"));
  Serial.println(F("===END TURNTABLE IR CONFIG (JSON)==="));
}

void runCapture() {
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) { results[i].captured = false; results[i].skipped = false; }
  Serial.println();
  Serial.println(F("=== Turntable remote capture ==="));
  Serial.print(F("I'll walk through ")); Serial.print(NUM_BUTTONS);
  Serial.println(F(" buttons. Point the remote at the receiver, up close."));
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) captureButton(i);
  printConfigJSON();
  Serial.println();
  Serial.println(F("Done. Copy the JSON block above into your config file."));
  Serial.println(F("Send any character to capture again."));
}

void setup() {
  Serial.begin(115200);
  IrReceiver.begin(IR_RECEIVE_PIN, ENABLE_LED_FEEDBACK);
  runCapture();
}

void loop() {
  if (Serial.available()) {
    while (Serial.available()) Serial.read();      // clear the trigger byte(s)
    runCapture();
  }
}

