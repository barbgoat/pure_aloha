#ifndef PURE_ALOHA_NODE_H
#define PURE_ALOHA_NODE_H

#include <Arduino.h>
#include <RadioLib.h>

#include "credentials_1.h"  // ← Troca para credentials_2.h, _3.h, _4.h conforme node

SPIClass SPI_LORA(FSPI);
SX1262 radio = new Module(10, 4, 41, 40, SPI_LORA);
LoRaWANNode node(&radio, &EU868);

#define PAYLOAD_SIZE    50

// Período fixo de transmissão (s) — igual em todos os nós
#if NODE_ID == 1
  #define TX_PERIOD_S 28
#elif NODE_ID == 2
  #define TX_PERIOD_S 30
#elif NODE_ID == 3
  #define TX_PERIOD_S 32
#elif NODE_ID == 4
  #define TX_PERIOD_S 34
#else
  #define TX_PERIOD_S 30
#endif

#endif