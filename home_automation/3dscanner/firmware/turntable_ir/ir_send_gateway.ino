/*
 * IR send gateway — turntable project
 * Library: IRremote v4.x   |   Board: Arduino Uno
 *
 * Reads simple commands over USB serial and blasts the matching IR frame.
 * It's protocol-generic on purpose: the laptop owns the code table (JSON),
 * this just transmits whatever it's told. One line per command, '\n' terminated.
 *
 * Commands:
 *   R <rawHex> [repeats]        send a 32-bit NEC frame exactly as captured
 *                               e.g.  R B847FF00        (POWER)
 *   N <addrHex> <cmdHex> [rep]  send NEC from address+command
 *                               e.g.  N 0 47
 *   PING                        -> replies PONG
 * Replies: "OK ..."  on success, "ERR ..." on problem.
 *
 * LED wiring (D3 is the Uno's fixed IR send pin):
 *   Short range (fine, turntable is adjacent):
 *     D3 --[100 ohm]-- IR-LED(+ anode) , IR-LED(- cathode) -- GND
 *   More range (uses your kit's 2N2222):
 *     D3 --[1k]-- base ; emitter -- GND ; collector -- IR-LED cathode ;
 *     IR-LED anode --[47 ohm]-- 5V
 *
 * Serial Monitor baud (if testing by hand): 115200
 */

#include <IRremote.hpp>

#define IR_SEND_PIN 3        // fixed on Uno (timer2)

String line;

void setup() {
  Serial.begin(115200);
  IrSender.begin(IR_SEND_PIN);
  Serial.println(F("IR-GATEWAY ready. R <rawHex> [rep] | N <addrHex> <cmdHex> [rep] | PING"));
}

void handle(String s) {
  s.trim();
  int sp1 = s.indexOf(' ');
  String cmd = (sp1 < 0) ? s : s.substring(0, sp1);
  cmd.toUpperCase();
  String rest = (sp1 < 0) ? "" : s.substring(sp1 + 1);
  rest.trim();

  if (cmd == "PING") { Serial.println(F("PONG")); return; }

  if (cmd == "R") {
    int sp = rest.indexOf(' ');
    String rawStr = (sp < 0) ? rest : rest.substring(0, sp);
    int rep = (sp < 0) ? 0 : rest.substring(sp + 1).toInt();
    uint32_t raw = strtoul(rawStr.c_str(), NULL, 16);
    if (raw == 0) { Serial.println(F("ERR bad raw")); return; }
    IrSender.sendNECRaw(raw, rep);
    Serial.print(F("OK R ")); Serial.println(rawStr);
    return;
  }

  if (cmd == "N") {
    int sp = rest.indexOf(' ');
    if (sp < 0) { Serial.println(F("ERR need addr and cmd")); return; }
    String addrStr = rest.substring(0, sp);
    String tail = rest.substring(sp + 1); tail.trim();
    int sp2 = tail.indexOf(' ');
    String cmdStr = (sp2 < 0) ? tail : tail.substring(0, sp2);
    int rep = (sp2 < 0) ? 0 : tail.substring(sp2 + 1).toInt();
    uint16_t addr = (uint16_t) strtoul(addrStr.c_str(), NULL, 16);
    uint16_t command = (uint16_t) strtoul(cmdStr.c_str(), NULL, 16);
    IrSender.sendNEC(addr, command, rep);
    Serial.print(F("OK N ")); Serial.print(addrStr);
    Serial.print(F(" ")); Serial.println(cmdStr);
    return;
  }

  Serial.println(F("ERR unknown cmd"));
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length()) { handle(line); line = ""; }
    } else if (line.length() < 40) {
      line += c;
    }
  }
}
