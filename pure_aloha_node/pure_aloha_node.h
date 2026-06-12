#ifndef PURE_ALOHA_NODE_H
#define PURE_ALOHA_NODE_H

#include <Arduino.h>
#include <RadioLib.h>

#include "credentials_1.h"  // ← Troca para credentials_2.h, _3.h, _4.h conforme node

SPIClass SPI_LORA(FSPI);
SX1262 radio = new Module(10, 4, 41, 40, SPI_LORA);
LoRaWANNode node(&radio, &EU868);

#define PAYLOAD_SIZE    50

// Período total inter-TX em ms (T_efetivo = sendReceive + wait_ms).
// O firmware subtrai sendReceive do delay, portanto TX_PERIOD_MS = T_efetivo.
// G alvo ≈ 0.026: sum(97ms / TX_PERIOD_i) = 0.00693+0.00669+0.00647+0.00626
#if NODE_ID == 1
  #define TX_PERIOD_MS 10000UL
#elif NODE_ID == 2
  #define TX_PERIOD_MS 14500UL
#elif NODE_ID == 3
  #define TX_PERIOD_MS 15000UL
#elif NODE_ID == 4
  #define TX_PERIOD_MS 15500UL
#else
  #define TX_PERIOD_MS 14750UL
#endif

#endif