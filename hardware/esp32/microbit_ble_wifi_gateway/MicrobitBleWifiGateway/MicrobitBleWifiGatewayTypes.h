#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>

struct MicrobitLink {
  const char* label;
  const char* address;
  uint8_t connIndex;
  NimBLEClient* client;
  NimBLERemoteCharacteristic* notifyChar;
  bool subscribed;
  uint32_t lastConnectAttemptMs;
  uint32_t lastPacketMs;
  int8_t lastRssi;
};
