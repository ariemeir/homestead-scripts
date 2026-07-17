/*                                                                                                                      
 * IR LED smoke test — fires the turntable POWER code every 2 seconds.
 * Board: Arduino Uno   |   Library: IRremote v4.x   |   Serial: 115200
 *
 * Wiring: D3 -[1k]- 2N2222 base ; emitter -> GND ; collector -> IR LED cathode (-)
 *         IR LED anode (+) -[100R]- 5V
 *
 * Expected: the turntable toggles on / off / on / off, once every 2 seconds.
 * The onboard pin-13 LED flashes on each transmit, so you can tell the sketch
 * is firing even though the IR itself is invisible.
 */

#include <IRremote.hpp>

#define IR_SEND_PIN 3          // fixed on Uno (timer2)

// Captured from your remote: POWER = NEC, addr 0x0, cmd 0x47
const uint32_t POWER_RAW = 0xB847FF00;

uint16_t shot = 0;

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  IrSender.begin(IR_SEND_PIN);
  Serial.println(F("POWER every 2s. Aim the LED at the turntable's IR window."));
  delay(1000);
}

void loop() {
  IrSender.sendNECRaw(POWER_RAW, 0); 

  digitalWrite(LED_BUILTIN, HIGH);
  delay(60);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.print(F("sent POWER #"));
  Serial.println(++shot);

  delay(2000);
}


