#include "pure_aloha_node.h"

//#define DEBUG_MODE

uint32_t tx_count = 0;
uint32_t rx_expected = 0;
uint32_t rx_success = 0;
uint32_t toa_real_ms = 0;
uint32_t interval_real_ms = 0;
uint32_t airtime_total_ms = 0;
uint8_t retry_count = 0;
uint32_t last_tx_ms = 0;
uint32_t tx_attempt_count = 0;
uint32_t last_sendreceive_ms = 0;


String stateDecode(int16_t result) {
  switch (result) {
    case RADIOLIB_ERR_NONE: return "OK";
    case RADIOLIB_ERR_RX_TIMEOUT: return "RX_TIMEOUT";
    case RADIOLIB_ERR_DOWNLINK_MALFORMED: return "DOWNLINK_MALFORMED";
    case RADIOLIB_ERR_INVALID_CID: return "INVALID_CID";
    case RADIOLIB_ERR_CRC_MISMATCH: return "CRC_MISMATCH";
    default: return "ERROR_" + String(result);
  }
}

void setup() {
  Serial.begin(115200);
  while(!Serial);
  delay(2000);
  
  Serial.println(F("\n[INIT] Pure ALOHA v3.0"));
  
  SPI_LORA.begin(7, 5, 6, 10);
  pinMode(42, OUTPUT);
  digitalWrite(42, HIGH);
  Serial.println(F("[INIT] SPI + GPIO42 OK"));

  Serial.print(F("[INIT] Node ID: "));
  Serial.println(NODE_ID);
  Serial.print(F("[INIT] TX Period (fixo): "));
  Serial.print(TX_PERIOD_MS / 1000.0, 1);
  Serial.println(F("s"));
  
  Serial.print(F("[INIT] DevEUI: "));
  Serial.println((uint32_t)(devEUI & 0xFFFFFFFF), HEX);
  
  pinMode(3, OUTPUT);
  digitalWrite(3, LOW);
  delay(100);
  digitalWrite(3, HIGH);
  delay(200);
  Serial.println(F("[INIT] Radio reset OK"));
  
  Serial.print(F("[INIT] Radio... "));
  int16_t state = radio.begin();
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print(F("FAILED "));
    Serial.println(state);
    while(true) delay(1000);
  }
  Serial.println(F("OK"));
  
  node.clearSession();
  node.beginOTAA(appEUI, devEUI, nwkKey, appKey);

  Serial.println(F("[JOIN] OTAA..."));
  while (true) {
    int s = node.activateOTAA();
    if (s == RADIOLIB_LORAWAN_NEW_SESSION) {
      Serial.println(F("[JOIN] OK!"));
      node.setADR(false);
      int dr = node.setDatarate(5);  // DR5 = SF7 BW125 — ADR desactivado para SF fixo
      Serial.printf("[DR]   setDatarate(5) = %d\n", dr);
      break;
    }
    Serial.printf("[JOIN] FAILED (%d) — retry 5s\n", s);
    for (int i = 0; i < 5; i++) { delay(1000); yield(); }
  }

  #ifdef DEBUG_MODE
    Serial.println(F("[MODE] Debug - delay()"));
  #else
    Serial.println(F("[MODE] Light Sleep"));
  #endif
  
  // SF7 BW125 50 bytes CR4/5 — fixo com setDatarate(5), não lê do rádio
  // (getTimeOnAir() após RX2 retorna SF do downlink, não do uplink)
  toa_real_ms = 97;
  Serial.print(F("[INIT] ToA (SF7 fixo): "));
  Serial.print(toa_real_ms);
  Serial.println(F("ms"));
  Serial.println(F("[INIT] Ready\n"));
}

void loop() {
  uint32_t now_ms = millis();
  if (last_tx_ms > 0) {
    interval_real_ms = now_ms - last_tx_ms;
  }

  tx_attempt_count++;  // conta TODAS as tentativas (base para calcular G oferecido)
  
  uint8_t payload[PAYLOAD_SIZE];
  payload[0] = NODE_ID;
  memcpy(&payload[1], &tx_count, 4);
  memcpy(&payload[5], &rx_expected, 4);
  memcpy(&payload[9], &rx_success, 4);
  memcpy(&payload[13], &toa_real_ms, 4);
  memcpy(&payload[17], &interval_real_ms, 4);
  memcpy(&payload[21], &airtime_total_ms, 4);
  payload[25] = retry_count;
  memcpy(&payload[26], &tx_attempt_count, 4);   // bytes 26-29: tentativas totais (para G)
  uint32_t node_millis = millis();
  memcpy(&payload[30], &node_millis, 4);         // bytes 30-33: timestamp local (ms)
  memcpy(&payload[34], &last_sendreceive_ms, 4);  // bytes 34-37: duração sendReceive anterior (ms)
  memset(&payload[38], 0x00, 12);
  
  Serial.print(F("[TX] Node "));
  Serial.print(NODE_ID);
  Serial.print(F(" attempt="));
  Serial.print(tx_attempt_count);
  Serial.print(F(" ok="));
  Serial.print(tx_count);
  
  if (toa_real_ms > 0) {
    Serial.print(F(" ToA="));
    Serial.print(toa_real_ms);
    Serial.print(F("ms"));
  }
  
  if (interval_real_ms > 0) {
    Serial.print(F(" ΔT="));
    Serial.print(interval_real_ms / 1000.0, 2);
    Serial.print(F("s"));
  }
  
  Serial.print(F(" ... "));
  
  uint32_t tx_start_ms = millis();
  int16_t state = node.sendReceive(payload, PAYLOAD_SIZE, 1, false);
  uint32_t tx_end_ms = millis();
  uint32_t sendreceive_ms = tx_end_ms - tx_start_ms;
  last_sendreceive_ms = sendreceive_ms;

  uint32_t toa_max = 8000;  // 8s: TX + RX1 + RX2 com margem realista

  bool tx_failed = (state < -1199);
  bool toa_high = (sendreceive_ms > toa_max);  // guard sobre sendReceive, não ToA RF

  if (tx_failed || toa_high) {
    if (tx_failed) {
      Serial.print(F("TX FAILED: "));
      Serial.println(stateDecode(state));
    } else {
      Serial.print(F("sendReceive HUNG: "));
      Serial.print(sendreceive_ms);
      Serial.print(F("ms > "));
      Serial.print(toa_max);
      Serial.println(F("ms"));
    }
    
    retry_count++;
    
    if (retry_count >= 3) {
      Serial.println(F("\n[REJOIN] 3 failures - rejoining..."));
      
      node.clearSession();
      node.beginOTAA(appEUI, devEUI, nwkKey, appKey);
      
      int rejoin_attempts = 0;
      bool rejoin_success = false;
      
      while (rejoin_attempts < 5) {
        int16_t rejoin_state = node.activateOTAA();
        if (rejoin_state != RADIOLIB_LORAWAN_NEW_SESSION) {
          Serial.print(F("[REJOIN] Join fail "));
          Serial.println(rejoin_attempts);
          rejoin_attempts++;
          delay(5000);
          continue;  // não tenta sendReceive com sessão inválida
        }

        uint8_t dummy[1] = {0xFF};
        int16_t test = node.sendReceive(dummy, 1, 1, false);

        if (test >= RADIOLIB_ERR_NONE || test == RADIOLIB_ERR_RX_TIMEOUT) {
          node.setADR(false);
          int dr = node.setDatarate(5);  // DR5 = SF7 BW125 — ADR desactivado
          Serial.printf("[DR]   setDatarate(5) = %d\n", dr);
          Serial.println(F("[REJOIN] OK\n"));
          retry_count = 0;
          last_tx_ms = 0;
          rejoin_success = true;
          break;
        }

        Serial.print(F("[REJOIN] Retry "));
        Serial.println(rejoin_attempts);
        yield();
        delay(5000);
        rejoin_attempts++;
      }
      
      if (!rejoin_success) {
        Serial.println(F("[REJOIN] FAILED - aguarda 60s"));
        retry_count = 0;
        delay(60000);
      }
      
      delay(TX_PERIOD_MS);
      return;
    }

    delay(TX_PERIOD_MS);
    return;
  }
  
  airtime_total_ms += toa_real_ms;
  last_tx_ms = tx_start_ms;  // início do TX para intervalo inter-partida correcto
  tx_count++;
  rx_expected++;
  retry_count = 0;
  
  Serial.print(F("OK"));
  
  if (state == RADIOLIB_ERR_NONE) {
    Serial.print(F(" (no DL, ToA="));
    Serial.print(toa_real_ms);
    Serial.println(F("ms)"));
  } else if (state > 0) {
    rx_success++;
    Serial.print(F(" (DL port "));
    Serial.print(state);
    Serial.print(F(", ToA="));
    Serial.print(toa_real_ms);
    Serial.println(F("ms)"));
  } else if (state == RADIOLIB_ERR_RX_TIMEOUT) {
    Serial.print(F(" (DL timeout, ToA="));
    Serial.print(toa_real_ms);
    Serial.println(F("ms)"));
  } else {
    Serial.print(F(" (DL error: "));
    Serial.print(stateDecode(state));
    Serial.print(F(", ToA="));
    Serial.print(toa_real_ms);
    Serial.println(F("ms)"));
  }
  
  // T_efetivo = TX_PERIOD_MS; subtrai sendReceive para manter período estável
  int32_t wait_ms = (int32_t)TX_PERIOD_MS - (int32_t)sendreceive_ms;
  if (wait_ms < 200) wait_ms = 200;

  #ifdef DEBUG_MODE
    Serial.print(F("[WAIT] "));
    Serial.print(wait_ms / 1000.0, 2);
    Serial.println(F("s\n"));
    delay((uint32_t)wait_ms);
  #else
    Serial.print(F("[SLEEP] "));
    Serial.print(wait_ms / 1000.0, 2);
    Serial.println(F("s\n"));
    Serial.flush();

    // v2 (corrigido): sem Serial.begin, guard 50ms, sem margem antecipação
    // uint64_t sleep_us = (uint64_t)wait_ms * 1000ULL;
    // if (sleep_us > 50000ULL) {
    //   esp_sleep_enable_timer_wakeup(sleep_us);
    //   esp_light_sleep_start();
    //   delay(5);
    // }

    // v1 (original): referência para comparação de autonomia
    esp_sleep_enable_timer_wakeup((uint64_t)wait_ms * 1000ULL);
    esp_light_sleep_start();
    Serial.begin(115200);
    delay(100);
    Serial.println(F("[WAKE] Back"));
  #endif
}