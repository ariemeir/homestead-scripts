/*
 * Universal IR blaster — Arduino Uno + KY-022 (D2) + IR LED via 2N2222 (D3)
 * Library: IRremote v4.x (Armin Joachimsmeyer)
 * Serial: 115200
 *
 * One board that both LEARNS remotes and BLASTS codes. The laptop owns the
 * code table (JSON); this firmware is deliberately protocol-generic so adding
 * a new device never means reflashing.
 *
 * Commands (one per line, '\n' terminated):
 *   PING                     -> PONG
 *   LEARN                    -> waits for one remote press, prints a JSON line
 *   MON                      -> monitor mode: prints every frame until any input
 *   R <rawHex> [repeats]     -> send 32-bit NEC frame as captured  (R B847FF00)
 *   N <addrHex> <cmdHex> [r] -> send NEC from address+command      (N 0 47)
 *   S <protocol> <addrHex> <cmdHex> [r]  -> send other protocols
 *                               protocol: SONY | RC5 | RC6 | SAMSUNG | JVC | PANASONIC
 * Replies begin with OK / ERR / LEARNED so the host can parse them.
 *
 * Wiring recap:
 *   KY-022: S->D2, +->5V, -->GND
 *   D3 -[1k]- 2N2222 base ; emitter->GND ; collector->IR LED cathode
 *   IR LED anode -[100R]- 5V      (parallel a 2nd 100R for more range)
 */

#include <IRremote.hpp>

#define IR_RECEIVE_PIN 2
#define IR_SEND_PIN    3      // fixed on Uno (timer2)

String line;

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

void printFrameJSON(const char* tag) {
  Serial.print(tag);
  Serial.print(F(" {\"protocol\": \"")); Serial.print(protoName(IrReceiver.decodedIRData.protocol));
  Serial.print(F("\", \"address\": ")); Serial.print(IrReceiver.decodedIRData.address);
  Serial.print(F(", \"command\": "));   Serial.print(IrReceiver.decodedIRData.command);
  Serial.print(F(", \"raw\": "));        Serial.print(IrReceiver.decodedIRData.decodedRawData);
  Serial.print(F(", \"bits\": "));       Serial.print(IrReceiver.decodedIRData.numberOfBits);
  Serial.println(F("}"));
}

// Wait for one genuine (non-repeat) frame. Returns false on timeout/abort.
bool learnOne(unsigned long timeoutMs) {
  unsigned long start = millis();
  IrReceiver.resume();
  while (millis() - start < timeoutMs) {
    if (Serial.available()) { while (Serial.available()) Serial.read(); return false; }
    if (IrReceiver.decode()) {
      bool isRepeat = IrReceiver.decodedIRData.flags &
                      (IRDATA_FLAGS_IS_REPEAT | IRDATA_FLAGS_IS_AUTO_REPEAT);
      if (!isRepeat) {
        printFrameJSON("LEARNED");
        // swallow trailing frames so one tap == one result
        unsigned long f = millis();
        while (millis() - f < 500) { if (IrReceiver.decode()) IrReceiver.resume(); }
        return true;
      }
      IrReceiver.resume();
    }
  }
  return false;
}

void monitor() {
  Serial.println(F("OK MON (send any character to stop)"));
  IrReceiver.resume();
  while (true) {
    if (Serial.available()) { while (Serial.available()) Serial.read(); break; }
    if (IrReceiver.decode()) {
      bool isRepeat = IrReceiver.decodedIRData.flags &
                      (IRDATA_FLAGS_IS_REPEAT | IRDATA_FLAGS_IS_AUTO_REPEAT);
      if (!isRepeat) printFrameJSON("FRAME");
      IrReceiver.resume();
    }
  }
  Serial.println(F("OK MON end"));
}


/*
 * TIMER2 GUARD — the important bit on an Uno.
 *
 * IRremote drives the sender's 38kHz PWM *and* the receiver's 50us sampling
 * interrupt from the same Timer2. If the receive ISR keeps firing while we
 * transmit, it steals cycles from the mark/space timing and the frame comes
 * out malformed: the IR LED still flashes, but nothing decodes it.
 *
 * So every transmit is wrapped — receiver off, send, receiver back on.
 *
 * If stopTimer()/restartTimer() don't compile on your IRremote version,
 * swap them for IrReceiver.stop() / IrReceiver.start().
 */
static inline void rxOff() {
  IrReceiver.stopTimer();
}

static inline void rxOn() {
  IrReceiver.restartTimer();
  IrReceiver.resume();
}

String nextTok(String& s) {
  s.trim();
  int sp = s.indexOf(' ');
  String tok = (sp < 0) ? s : s.substring(0, sp);
  s = (sp < 0) ? "" : s.substring(sp + 1);
  return tok;
}

void sendOther(String proto, uint16_t addr, uint16_t cmd, int rep) {
  proto.toUpperCase();
  if      (proto == "SONY")      IrSender.sendSony(addr, cmd, rep);
  else if (proto == "RC5")       IrSender.sendRC5(addr, cmd, rep);
  else if (proto == "RC6")       IrSender.sendRC6(addr, cmd, rep);
  else if (proto == "SAMSUNG")   IrSender.sendSamsung(addr, cmd, rep);
  else if (proto == "JVC")       IrSender.sendJVC((uint8_t)addr, (uint8_t)cmd, rep);
  else if (proto == "PANASONIC") IrSender.sendPanasonic(addr, cmd, rep);
  else { Serial.println(F("ERR unknown protocol")); return; }
  Serial.print(F("OK S ")); Serial.println(proto);
}

void handle(String s) {
  s.trim();
  String cmd = nextTok(s);
  cmd.toUpperCase();

  if (cmd == "PING") { Serial.println(F("PONG")); return; }

  if (cmd == "LEARN") {
    Serial.println(F("OK LEARN press a button..."));
    if (!learnOne(30000UL)) Serial.println(F("ERR learn timeout"));
    return;
  }

  if (cmd == "MON") { monitor(); return; }

  if (cmd == "R") {
    String rawStr = nextTok(s);
    int rep = s.length() ? nextTok(s).toInt() : 0;
    uint32_t raw = strtoul(rawStr.c_str(), NULL, 16);
    if (raw == 0) { Serial.println(F("ERR bad raw")); return; }
    rxOff();
    IrSender.sendNECRaw(raw, rep);
    rxOn();
    Serial.print(F("OK R ")); Serial.println(rawStr);
    return;
  }

  if (cmd == "N") {
    String addrStr = nextTok(s);
    String cmdStr  = nextTok(s);
    if (!addrStr.length() || !cmdStr.length()) { Serial.println(F("ERR need addr and cmd")); return; }
    int rep = s.length() ? nextTok(s).toInt() : 0;
    rxOff();
    IrSender.sendNEC((uint16_t)strtoul(addrStr.c_str(), NULL, 16),
                     (uint16_t)strtoul(cmdStr.c_str(), NULL, 16), rep);
    rxOn();
    Serial.print(F("OK N ")); Serial.print(addrStr);
    Serial.print(F(" "));     Serial.println(cmdStr);
    return;
  }

  if (cmd == "S") {
    String proto   = nextTok(s);
    String addrStr = nextTok(s);
    String cmdStr  = nextTok(s);
    if (!cmdStr.length()) { Serial.println(F("ERR need protocol addr cmd")); return; }
    int rep = s.length() ? nextTok(s).toInt() : 0;
    rxOff();
    sendOther(proto, (uint16_t)strtoul(addrStr.c_str(), NULL, 16),
                     (uint16_t)strtoul(cmdStr.c_str(), NULL, 16), rep);
    rxOn();
    return;
  }

  Serial.println(F("ERR unknown cmd"));
}

void setup() {
  Serial.begin(115200);
  IrReceiver.begin(IR_RECEIVE_PIN, ENABLE_LED_FEEDBACK);
  IrSender.begin(IR_SEND_PIN);
  Serial.println(F("IR-BLASTER ready. PING | LEARN | MON | R <hex> | N <addr> <cmd> | S <proto> <addr> <cmd>"));
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { if (line.length()) { handle(line); line = ""; } }
    else if (line.length() < 60) line += c;
  }
}
