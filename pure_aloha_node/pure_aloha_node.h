#ifndef PURE_ALOHA_NODE_H
#define PURE_ALOHA_NODE_H

#include <Arduino.h>
#include <RadioLib.h>

#include "credentials_1.h"  // ← Troca para credentials_2.h, _3.h, _4.h conforme node

SPIClass SPI_LORA(FSPI);
SX1262 radio = new Module(10, 4, 41, 40, SPI_LORA);
LoRaWANNode node(&radio, &EU868);

#define PAYLOAD_SIZE    50

// Período fixo em ms — evita truncagem de floats em delay()
// (14.5 * 1000UL truncaria para 14000 em C++)
#if NODE_ID == 1
  #define TX_PERIOD_MS 14000UL
#elif NODE_ID == 2
  #define TX_PERIOD_MS 14500UL
#elif NODE_ID == 3
  #define TX_PERIOD_MS 15000UL
#elif NODE_ID == 4
  #define TX_PERIOD_MS 15500UL
#else
  #define TX_PERIOD_MS 15000UL
#endif

#endif