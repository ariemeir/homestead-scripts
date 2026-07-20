/*
 * WifeSignal - single-button BLE bring-up test
 * Board:  ESP32-C3 SuperMini (ESP32C3 Dev Module, USB CDC On Boot = Enabled)
 * BLE:    NimBLE-Arduino v2.x
 *
 * One on/off STATE drives BOTH the onboard LED and the arcade lamp:
 *   - switch on GPIO3 (press = LOW, internal pull-up) toggles state
 *   - onboard LED on GPIO8 (INVERTED, LOW = ON) mirrors state
 *   - arcade lamp on GPIO6 -> 1k -> S8050 base -> LED- ; LED+ -> 5V (as built: LOW = ON)
 *   - a BLE central can WRITE (1/0), READ, and gets NOTIFY on every change
 *
 * Common ground is mandatory: ESP32 GND, S8050 emitter, switch GND, 5V return.
 */

#include <NimBLEDevice.h>

#define SVC_UUID   "6d5f0001-4b6b-4a3a-9e1e-2a7b1c9f0001"
#define STATE_UUID "6d5f0002-4b6b-4a3a-9e1e-2a7b1c9f0002"

const int BTN  = 3;    // switch: NO -> GPIO3, COM -> GND
const int LEDB = 8;    // onboard LED, INVERTED (LOW = ON)
const int LAMP = 6;    // GPIO6 -> 1k -> S8050 base (as built: LOW = lamp ON)

NimBLECharacteristic* stateChar = nullptr;
bool state = false;
bool connected = false;

// debounce
int lastRead = HIGH;
uint32_t lastEdge = 0;
bool handled = false;

void applyLED() {
  digitalWrite(LEDB, state ? LOW  : HIGH);   // onboard: inverted
  digitalWrite(LAMP, state ? LOW  : HIGH);   // arcade lamp: wired active-low (LOW = lamp ON)
}

void pushState(bool doNotify) {
  uint8_t v = state ? 1 : 0;
  stateChar->setValue(&v, 1);
  if (doNotify && connected) stateChar->notify();
}

class StateCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo& info) override {
    std::string v = c->getValue();
    if (v.empty()) return;
    state = (v[0] != 0);
    applyLED();
    pushState(true);
    Serial.printf("write -> state %d\n", state);
  }
};

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& i) override {
    connected = true; Serial.println("central connected");
  }
  void onDisconnect(NimBLEServer* s, NimBLEConnInfo& i, int reason) override {
    connected = false; Serial.println("central disconnected");
    NimBLEDevice::startAdvertising();
  }
};

void setup() {
  Serial.begin(115200);
  pinMode(BTN, INPUT_PULLUP);
  pinMode(LEDB, OUTPUT);
  pinMode(LAMP, OUTPUT);
  applyLED();

  Serial.printf("pins -> BTN=%d  LEDB=%d  LAMP=%d\n", BTN, LEDB, LAMP);

  NimBLEDevice::init("WifeSignal");
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);

  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(SVC_UUID);
  stateChar = svc->createCharacteristic(STATE_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY);
  stateChar->setCallbacks(new StateCallbacks());
  pushState(false);
  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->setMinInterval(160);   // 100 ms
  adv->setMaxInterval(320);   // 200 ms
  adv->setName("WifeSignal");
  adv->start();
  Serial.println("BLE up - advertising as WifeSignal");
}

void loop() {
  uint32_t now = millis();
  int r = digitalRead(BTN);
  if (r != lastRead) { lastRead = r; lastEdge = now; }
  if (now - lastEdge > 40) {
    if (r == LOW && !handled) {
      handled = true;
      state = !state;
      applyLED();
      pushState(true);
      Serial.printf("press -> state %d\n", state);
    } else if (r == HIGH) {
      handled = false;
    }
  }
  delay(5);
}
