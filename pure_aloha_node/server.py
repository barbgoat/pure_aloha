#!/usr/bin/env python3
"""
Pure ALOHA Server
Version 3.2 - Métricas para comparação CW-ALOHA
"""

from flask import Flask, request, jsonify
from datetime import datetime as dt, timedelta
import csv
import base64
import math
import os
import re
import signal
import statistics
import threading
import requests

app = Flask(__name__)


def parse_ts(ts: str) -> dt:
    """Parseia timestamps do ChirpStack com precisão nanosegundo (9 casas decimais).
    datetime.fromisoformat() suporta no máximo 6 casas em Python < 3.11 — trunca."""
    ts = ts.replace('Z', '+00:00')
    ts = re.sub(r'(\.\d{6})\d+', r'\1', ts)
    return dt.fromisoformat(ts)

LOCK = threading.Lock()
SESSION_DATA = []
SESSION_START = None
NODE_COUNTERS = {}
TOTAL_COLLISIONS = 0
ACTIVE_DEVICES = {}
JOIN_EVENTS = []
GLOBAL_TIMESTAMPS_LOG = []

CHIRPSTACK_API = "http://192.168.0.1:8090/api"
API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJjaGlycHN0YWNrIiwiaXNzIjoiY2hpcnBzdGFjayIsInN1YiI6Ijg0ZDE4NmMyLTIxMmMtNDUyNC1iYTlhLWRiYWJlMDc1NTcwYiIsInR5cCI6ImtleSJ9.M9eNakDVt0NjYIJxlBXjF2yZlq_Y0lDK-87Hjjcg9Zk"


def compute_toa_ms(sf: int, bw_hz: int, payload_bytes: int,
                   n_preamble: int = 8, cr: int = 1,
                   crc: int = 1, ih: int = 0) -> float:
    """Calcula Time on Air físico (Semtech formula)"""
    de = 1 if sf >= 11 else 0
    t_sym_ms = (2 ** sf) / (bw_hz / 1000.0)
    t_preamble_ms = (n_preamble + 4.25) * t_sym_ms
    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * ih
    denominator = 4 * (sf - 2 * de)
    n_payload = 8 + max(math.ceil(numerator / denominator) * (cr + 4), 0)
    t_payload_ms = n_payload * t_sym_ms
    return round(t_preamble_ms + t_payload_ms, 3)


def flush_device_nonces(dev_eui):
    """Flush OTAA nonces ChirpStack"""
    if not API_KEY:
        return False

    url = f"{CHIRPSTACK_API}/devices/{dev_eui}/dev-nonces"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            print(f"[FLUSH] Device {dev_eui[-8:]} nonces cleared")
            return True
        else:
            print(f"[FLUSH] Failed {dev_eui[-8:]}: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FLUSH] Error {dev_eui[-8:]}: {e}")
        return False


def extract_radio_params(data: dict) -> dict:
    """Extrai parâmetros rádio do webhook ChirpStack"""
    tx_info = data.get('txInfo', {})
    frequency_hz = tx_info.get('frequency')
    lora = tx_info.get('modulation', {}).get('lora', {})
    sf = lora.get('spreadingFactor')
    bw = lora.get('bandwidth')
    toa_ms = None
    if sf and bw:
        # 50 bytes — mesmo valor em ambos os protocolos para comparação justa
        toa_ms = compute_toa_ms(sf, bw, payload_bytes=50)
    return {
        'sf': sf,
        'bw_hz': bw,
        'bw_khz': round(bw / 1000, 1) if bw else None,
        'frequency_mhz': round(frequency_hz / 1e6, 3) if frequency_hz else None,
        'toa_teorico_ms': toa_ms,
    }


@app.route('/webhook', methods=['POST'])
def webhook():
    with LOCK:
        try:
            global SESSION_START, TOTAL_COLLISIONS

            if SESSION_START is None:
                SESSION_START = dt.now()
                print(f"\n[SESSION] Started at {SESSION_START.strftime('%Y-%m-%d %H:%M:%S')}\n")

            data = request.json
            event = request.args.get('event') or data.get('event')
            dev_eui = data.get('deviceInfo', {}).get('devEui', 'unknown')

            if event == 'join':
                timestamp = data.get('time', dt.now().isoformat())
                JOIN_EVENTS.append({'timestamp': timestamp, 'dev_eui': dev_eui, 'event': 'join'})

                if dev_eui in NODE_COUNTERS:
                    old = NODE_COUNTERS[dev_eui]

                    if API_KEY and old.get('session_id', 1) >= 3:
                        print(f"[AUTO-FLUSH] Device {dev_eui[-8:]} session {old['session_id']} - flushing...")
                        flush_device_nonces(dev_eui)

                    old_session = {
                        'session_id': old['session_id'],
                        'fcnt_start': 0,
                        'fcnt_end': old['last_fcnt'],
                        'tx_total': old['last_fcnt'] + 1,
                        'collisions': old['collisions'],
                        'end_timestamp': timestamp,
                    }
                    NODE_COUNTERS[dev_eui].setdefault('sessions', []).append(old_session)
                    print(f"[REJOIN] Device {dev_eui[-8:]} session {old['session_id']} -> {old['session_id']+1}")
                    NODE_COUNTERS[dev_eui]['last_fcnt'] = -1
                    NODE_COUNTERS[dev_eui]['collisions'] = 0
                    NODE_COUNTERS[dev_eui]['rx_count'] = 0
                    NODE_COUNTERS[dev_eui]['session_id'] += 1
                else:
                    print(f"[JOIN] Device {dev_eui[-8:]} joined")

                return jsonify({'status': 'ok'}), 200

            if event != 'up':
                return jsonify({'status': 'ignored'}), 200

            timestamp = data.get('time', dt.now().isoformat())
            f_cnt = data.get('fCnt', 0)
            rx_info = data.get('rxInfo', [{}])[0]
            rssi = rx_info.get('rssi', 0)
            snr = rx_info.get('snr', 0)

            payload_b64 = data.get('data', '')
            node_id = rx_expected = rx_success = tx_count = None
            transacao_real_ms = interval_real_ms = airtime_total_ms = None
            retry_count = 0

            tx_attempt_count = None
            node_millis = None
            sendreceive_ms = None

            if payload_b64:
                payload_bytes = base64.b64decode(payload_b64)
                if len(payload_bytes) >= 26:
                    node_id = payload_bytes[0]
                    tx_count = int.from_bytes(payload_bytes[1:5], 'little')
                    rx_expected = int.from_bytes(payload_bytes[5:9], 'little')
                    rx_success = int.from_bytes(payload_bytes[9:13], 'little')
                    transacao_real_ms = int.from_bytes(payload_bytes[13:17], 'little')
                    interval_real_ms = int.from_bytes(payload_bytes[17:21], 'little')
                    airtime_total_ms = int.from_bytes(payload_bytes[21:25], 'little')
                    retry_count = payload_bytes[25]
                    ACTIVE_DEVICES[node_id] = dev_eui
                if len(payload_bytes) >= 30:
                    tx_attempt_count = int.from_bytes(payload_bytes[26:30], 'little')
                if len(payload_bytes) >= 34:
                    node_millis = int.from_bytes(payload_bytes[30:34], 'little')
                if len(payload_bytes) >= 38:
                    sendreceive_ms = int.from_bytes(payload_bytes[34:38], 'little') or None

            radio = extract_radio_params(data)
            sf = radio['sf']
            bw_khz = radio['bw_khz']
            toa_teorico_ms = radio['toa_teorico_ms']

            collisions_detected = 0
            PERIODOS_NOMINAIS = {1: 28, 2: 30, 3: 32, 4: 34}

            if dev_eui not in NODE_COUNTERS:
                NODE_COUNTERS[dev_eui] = {
                    'last_fcnt': f_cnt,
                    'tx_count': tx_count or 0,
                    'collisions': 0,
                    'rx_count': 1,
                    'node_id': node_id,
                    'periodo_nominal_s': PERIODOS_NOMINAIS.get(node_id, 30),
                    'session_id': 1,
                    'sessions': [],
                    'sf': sf,
                    'bw_khz': bw_khz,
                    'toa_teorico_ms': toa_teorico_ms,
                    'toa_teo_acumulado_ms': 0,
                    'intervals': [],
                    'last_ts': timestamp,
                    'transacao_real_list': [],
                    'interval_real_list': [],
                    'retry_list': [],
                    'sendreceive_list': [],
                    'last_tx_attempt_count': tx_attempt_count,
                }
                print(f"[NEW NODE] No {node_id} FCnt={f_cnt} SF={sf} BW={bw_khz}kHz ToA={toa_teorico_ms}ms")
            else:
                nc = NODE_COUNTERS[dev_eui]
                expected_fcnt = nc['last_fcnt'] + 1

                if sf and nc.get('sf') != sf:
                    print(f"[ADR] No {node_id} SF changed: {nc.get('sf')} -> {sf}")
                    nc['sf'] = sf
                    nc['bw_khz'] = bw_khz
                    nc['toa_teorico_ms'] = toa_teorico_ms

                try:
                    ts_prev = parse_ts(nc['last_ts'])
                    ts_curr = parse_ts(timestamp)
                    interval_s = (ts_curr - ts_prev).total_seconds()
                    if 1 < interval_s < 3600:
                        nc['intervals'].append(interval_s)
                except Exception:
                    pass
                nc['last_ts'] = timestamp

                if f_cnt < nc['last_fcnt']:
                    print(f"[RESET] No {node_id} FCnt: {nc['last_fcnt']} -> {f_cnt}")
                    old_session = {
                        'session_id': nc['session_id'],
                        'fcnt_start': 0,
                        'fcnt_end': nc['last_fcnt'],
                        'tx_total': nc['last_fcnt'] + 1,
                        'collisions': nc['collisions'],
                        'end_timestamp': timestamp,
                    }
                    nc.setdefault('sessions', []).append(old_session)
                    nc['last_fcnt'] = f_cnt
                    nc['collisions'] = 0
                    nc['rx_count'] = 1
                    nc['session_id'] += 1

                elif f_cnt > expected_fcnt:
                    collisions_detected = f_cnt - expected_fcnt
                    nc['collisions'] += collisions_detected
                    TOTAL_COLLISIONS += collisions_detected
                    print(f"[COLLISION] No {node_id} lost {collisions_detected} frame(s) (FCnt: {expected_fcnt}->{f_cnt})")

                nc['last_fcnt'] = f_cnt
                nc['rx_count'] = nc.get('rx_count', 0) + 1
                if tx_count is not None:
                    nc['tx_count'] = tx_count
                if tx_attempt_count is not None:
                    nc['last_tx_attempt_count'] = tx_attempt_count

                if transacao_real_ms and transacao_real_ms > 0:
                    nc['transacao_real_list'].append(transacao_real_ms)
                if interval_real_ms and interval_real_ms > 0:
                    nc['interval_real_list'].append(interval_real_ms)
                if retry_count:
                    nc['retry_list'].append(retry_count)
                # sendreceive_ms: filtra 0 (primeiro frame não tem medição anterior)
                if sendreceive_ms and sendreceive_ms > 100:
                    nc.setdefault('sendreceive_list', []).append(sendreceive_ms)

            if toa_teorico_ms:
                NODE_COUNTERS[dev_eui]['toa_teo_acumulado_ms'] += toa_teorico_ms

            sensitivity_map = {7: -120, 8: -123, 9: -126, 10: -129, 11: -132, 12: -137}
            sensitivity = sensitivity_map.get(sf, -120)
            link_margin = rssi - sensitivity if rssi else None

            # FIX: PDR uplink calculado como (FCnt+1 - colisoes) / (FCnt+1), não sempre 100%
            nc = NODE_COUNTERS[dev_eui]
            _fcnt_total = f_cnt + 1
            _fcnt_lost = nc['collisions']
            pdr_uplink = round((_fcnt_total - _fcnt_lost) / _fcnt_total * 100, 2) if _fcnt_total > 0 else None

            pdr_downlink = None
            if rx_expected is not None and rx_expected >= 0:
                actual_expected = rx_expected + 1
                pdr_downlink = round((rx_success / actual_expected) * 100.0, 2) if actual_expected > 0 else None

            frame = {
                'timestamp': timestamp,
                'dev_eui': dev_eui,
                'node_id': node_id,
                'f_cnt': f_cnt,
                'session_id': NODE_COUNTERS[dev_eui]['session_id'],
                'tx_count': tx_count,
                'rx_expected': rx_expected,
                'rx_success': rx_success,
                'pdr_uplink': pdr_uplink,
                'pdr_downlink': pdr_downlink,
                'rssi': rssi,
                'snr': snr,
                'collisions_detected': collisions_detected,
                'sf': sf,
                'bw_khz': bw_khz,
                'toa_teorico_ms': toa_teorico_ms,
                'frequency_mhz': radio['frequency_mhz'],
                'transacao_real_ms': transacao_real_ms,
                'interval_real_ms': interval_real_ms,
                'airtime_total_ms': airtime_total_ms,
                'retry_count': retry_count,
                'collision_free': collisions_detected == 0,
                'tx_attempt_count': tx_attempt_count,
                'node_millis': node_millis,
                'sendreceive_ms': sendreceive_ms,
                'link_margin_db': round(link_margin, 1) if link_margin else None,
            }

            GLOBAL_TIMESTAMPS_LOG.append({
                'timestamp': timestamp,
                'node_id': node_id,
                'fcnt': f_cnt,
                'sf': sf,
                'toa_teorico_ms': toa_teorico_ms,
                'rssi': rssi,
                'snr': snr,
            })

            SESSION_DATA.append(frame)

            # ===== MÉTRICAS TEMPO REAL =====
            nc = NODE_COUNTERS[dev_eui]
            periodo_nominal = nc.get('periodo_nominal_s', 28)

            duty_cycle_rf = 0
            if toa_teorico_ms and periodo_nominal:
                duty_cycle_rf = (toa_teorico_ms / (periodo_nominal * 1000)) * 100

            ocupacao_no = 0
            if transacao_real_ms and interval_real_ms and interval_real_ms > 0:
                ocupacao_no = (transacao_real_ms / interval_real_ms) * 100

            utilizacao_canal = 0
            if SESSION_START:
                duration_s = (dt.now() - SESSION_START).total_seconds()
                if duration_s > 0:
                    total_toa_teo_s = sum(
                        stats.get('toa_teo_acumulado_ms', 0) / 1000.0
                        for stats in NODE_COUNTERS.values()
                    )
                    utilizacao_canal = (total_toa_teo_s / duration_s) * 100

            col_str = f" +{collisions_detected} COLISAO" if collisions_detected else ""

            freq_str = f" {radio['frequency_mhz']}MHz" if radio.get('frequency_mhz') else ""
            sr_str = f" SR={sendreceive_ms}ms" if sendreceive_ms else ""
            print(f"[RX] No {node_id} | FCnt={f_cnt} SF={sf}{freq_str} | "
                  f"ToA_Teo={toa_teorico_ms}ms Trans={transacao_real_ms}ms{sr_str} | "
                  f"RSSI={rssi}dBm SNR={snr}dB{col_str} | "
                  f"PDR={pdr_uplink}% Duty={duty_cycle_rf:.1f}% Canal={utilizacao_canal:.1f}%")

            return jsonify({'status': 'ok'}), 200

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'status': 'error'}), 500


@app.route('/status', methods=['GET'])
def status():
    with LOCK:
        duration_s = (dt.now() - SESSION_START).total_seconds() if SESSION_START else 0

        nodes_info = {}
        for dev_eui, stats in NODE_COUNTERS.items():
            transacao_avg = round(sum(stats['transacao_real_list'])/len(stats['transacao_real_list']), 1) if stats['transacao_real_list'] else None
            intervals = stats.get('interval_real_list', [])
            avg_period = round(sum(intervals) / len(intervals) / 1000, 1) if intervals else None
            nodes_info[dev_eui[-8:]] = {
                'node_id': stats['node_id'],
                'sf': stats.get('sf'),
                'toa_teo_ms': stats.get('toa_teorico_ms'),
                'transacao_real_ms': transacao_avg,
                'avg_period_s': avg_period,
                'last_fcnt': stats['last_fcnt'],
                'collisions': stats['collisions'],
                'session_id': stats['session_id'],
            }

        return jsonify({
            'protocol': 'Pure ALOHA v3.1',
            'session_start': SESSION_START.isoformat() if SESSION_START else None,
            'duration_min': round(duration_s / 60, 1),
            'frames_logged': len(SESSION_DATA),
            'total_collisions': TOTAL_COLLISIONS,
            'join_events': len(JOIN_EVENTS),
            'nodes': nodes_info,
        })


def detect_temporal_collisions(frames):
    """Detecta colisões via overlap temporal de transmissões"""
    frames_sorted = sorted(frames, key=lambda f: f.get('timestamp', ''))
    temporal_collisions = []

    for i in range(1, len(frames_sorted)):
        atual = frames_sorted[i]
        anterior = frames_sorted[i-1]

        try:
            ts_rx_atual = parse_ts(atual['timestamp'])
            ts_rx_anterior = parse_ts(anterior['timestamp'])

            toa_atual_s = atual.get('toa_teorico_ms', 616) / 1000.0
            # FIX: era datetime.timedelta (AttributeError silencioso) — corrigido para timedelta
            tx_start_atual = ts_rx_atual - timedelta(seconds=toa_atual_s)

            if tx_start_atual < ts_rx_anterior:
                overlap_s = (ts_rx_anterior - tx_start_atual).total_seconds()
                temporal_collisions.append({
                    'timestamp': atual['timestamp'],
                    'node_atual': atual.get('node_id'),
                    'fcnt_atual': atual.get('f_cnt'),
                    'node_anterior': anterior.get('node_id'),
                    'fcnt_anterior': anterior.get('f_cnt'),
                    'overlap_s': round(overlap_s, 3),
                    'sf_atual': atual.get('sf'),
                    'sf_anterior': anterior.get('sf'),
                })
        except Exception:
            pass

    return temporal_collisions


def export_session():
    # FIX: lock adquirido para evitar race condition com webhooks durante o export
    with LOCK:
        if not SESSION_DATA:
            print("[EXPORT] No data")
            return

        results_dir = "teste_pure_aloha"
        os.makedirs(results_dir, exist_ok=True)
        ts = dt.now().strftime("%Y%m%d_%H%M%S")

        csv_path           = os.path.join(results_dir, f"pure_aloha_{ts}.csv")
        summary_path       = os.path.join(results_dir, f"summary_{ts}.csv")
        nodes_path         = os.path.join(results_dir, f"nodes_{ts}.csv")
        collisions_path    = os.path.join(results_dir, f"collisions_{ts}.csv")
        joins_path         = os.path.join(results_dir, f"joins_{ts}.csv")
        metrics_path       = os.path.join(results_dir, f"metrics_{ts}.csv")
        airtime_path       = os.path.join(results_dir, f"airtime_{ts}.csv")
        temporal_cols_path = os.path.join(results_dir, f"temporal_collisions_{ts}.csv")
        sf_dist_path       = os.path.join(results_dir, f"sf_distribution_{ts}.csv")
        global_ts_path     = os.path.join(results_dir, f"global_timestamps_{ts}.csv")

        # FIX: calculado uma vez e passado às duas funções — antes chamado duas vezes
        temporal_cols = detect_temporal_collisions(SESSION_DATA)

        _export_raw_csv(csv_path)
        _export_summary_csv(summary_path, temporal_cols)
        _export_nodes_csv(nodes_path)
        _export_collisions_csv(collisions_path)
        _export_joins_csv(joins_path)
        _export_metrics_csv(metrics_path)
        _export_airtime_csv(airtime_path)
        _export_temporal_collisions_csv(temporal_cols_path, temporal_cols)
        _export_sf_distribution_csv(sf_dist_path)
        _export_global_timestamps_csv(global_ts_path)

        print(f"\n{'='*70}")
        print(f"  EXPORT COMPLETE")
        print(f"  Raw:               {csv_path}")
        print(f"  Summary:           {summary_path}")
        print(f"  Nodes:             {nodes_path}")
        print(f"  Metrics:           {metrics_path}")
        print(f"  Airtime:           {airtime_path}")
        print(f"  Collisions (FCnt): {collisions_path}")
        print(f"  Collisions (Temp): {temporal_cols_path}")
        print(f"  Joins:             {joins_path}")
        print(f"  SF Distribution:   {sf_dist_path}")
        print(f"  Global Timestamps: {global_ts_path}")
        print(f"{'='*70}\n")


def _compute_window_stats(frames_sorted, window_size=20):
    """G e S por sliding window de window_size frames ordenados por timestamp.
    G = (arrivals_in_window × ToA_avg) / (window_dur × 1000)
    S = (collision_free_in_window × ToA_avg) / (window_dur × 1000)
    """
    results = []
    for i in range(len(frames_sorted)):
        window = frames_sorted[max(0, i - window_size + 1):i + 1]
        if len(window) < 2:
            results.append({'G_window': None, 'S_window': None})
            continue
        try:
            t_start = parse_ts(window[0]['timestamp'])
            t_end   = parse_ts(window[-1]['timestamp'])
            window_dur_s = (t_end - t_start).total_seconds()
        except Exception:
            results.append({'G_window': None, 'S_window': None})
            continue
        if window_dur_s <= 0:
            results.append({'G_window': None, 'S_window': None})
            continue
        toa_vals = [f['toa_teorico_ms'] for f in window if f.get('toa_teorico_ms')]
        toa_avg  = sum(toa_vals) / len(toa_vals) if toa_vals else 0
        if toa_avg == 0:
            results.append({'G_window': None, 'S_window': None})
            continue
        total_arrivals = len(window) + sum(f.get('collisions_detected', 0) for f in window)
        rx_ok = sum(1 for f in window
                    if f.get('collision_free', f.get('collisions_detected', 0) == 0))
        G = total_arrivals * toa_avg / (window_dur_s * 1000)
        S = rx_ok          * toa_avg / (window_dur_s * 1000)
        results.append({'G_window': round(G, 4), 'S_window': round(S, 4)})
    return results


def _export_raw_csv(path):
    frames_sorted = sorted(SESSION_DATA, key=lambda f: f.get('timestamp', ''))
    window_stats  = _compute_window_stats(frames_sorted)

    with open(path, 'w', newline='') as f:
        fields = [
            'timestamp', 'dev_eui', 'node_id', 'session_id', 'f_cnt',
            'tx_count', 'rx_expected', 'rx_success',
            'pdr_uplink', 'pdr_downlink',
            'rssi', 'snr', 'link_margin_db',
            'collisions_detected', 'collision_free',
            'sf', 'bw_khz', 'toa_teorico_ms', 'frequency_mhz',
            'transacao_real_ms', 'interval_real_ms', 'airtime_total_ms', 'retry_count',
            'tx_attempt_count', 'node_millis', 'sendreceive_ms',
            'G_window', 'S_window',
        ]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for frame, ws in zip(frames_sorted, window_stats):
            row = dict(frame)
            row['collision_free'] = frame.get('collision_free', frame.get('collisions_detected', 0) == 0)
            row['G_window'] = ws['G_window']
            row['S_window'] = ws['S_window']
            writer.writerow(row)
    print(f"[EXPORT] Raw: {path} ({len(SESSION_DATA)} frames)")


def _export_metrics_csv(path):
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'node_id', 'dev_eui',
            'toa_teorico_ms', 'duty_cycle_rf_%', 'ocupacao_no_%',
            'periodo_nominal_s', 'periodo_real_avg_s', 'interval_std_s',
            'sr_teorico_ms', 'sr_avg_ms', 'sr_std_ms', 'sr_min_ms', 'sr_max_ms',
            'sr_elevado_n', 'sr_elevado_%',
            'link_margin_avg_db', 'link_margin_min_db',
        ])

        for dev_eui, stats in sorted(NODE_COUNTERS.items(), key=lambda x: x[1]['node_id']):
            node_id  = stats['node_id']
            toa_teo  = stats.get('toa_teorico_ms', 616)

            interval_list    = stats.get('interval_real_list', [])
            periodo_real_avg = round(sum(interval_list)/len(interval_list)/1000, 2) if interval_list else None
            periodo_nom      = stats.get('periodo_nominal_s', 28)
            jitter           = round(statistics.stdev(interval_list) / 1000, 3) if len(interval_list) > 1 else None

            duty_cycle_rf = round((toa_teo / (periodo_nom * 1000)) * 100, 2)
            ocupacao_no   = round((toa_teo / (periodo_real_avg * 1000)) * 100, 2) if periodo_real_avg else None

            node_frames = [f for f in SESSION_DATA if f['dev_eui'] == dev_eui and f.get('link_margin_db')]
            margins     = [f['link_margin_db'] for f in node_frames]
            margin_avg  = round(sum(margins)/len(margins), 1) if margins else None
            margin_min  = round(min(margins), 1) if margins else None

            # sendreceive: teórico mínimo = ToA + RX1_delay(1000ms) conforme spec LoRaWAN
            # A diferença sr_avg - sr_teorico representa a janela RX1 do RadioLib
            sr_list    = stats.get('sendreceive_list', [])
            sr_teorico = round(toa_teo + 1000, 1)
            sr_avg     = round(sum(sr_list)/len(sr_list), 1) if sr_list else None
            sr_std     = round(statistics.stdev(sr_list), 1) if len(sr_list) > 1 else None
            sr_min     = round(min(sr_list), 1) if sr_list else None
            sr_max     = round(max(sr_list), 1) if sr_list else None
            # SR elevado (>2000ms) indica actividade detectada na janela RX (colisão/DL)
            sr_elevado_n   = sum(1 for s in sr_list if s > 2000)
            sr_elevado_pct = round(sr_elevado_n / len(sr_list) * 100, 2) if sr_list else None

            writer.writerow([
                node_id, dev_eui,
                toa_teo, duty_cycle_rf, ocupacao_no,
                periodo_nom, periodo_real_avg, jitter,
                sr_teorico, sr_avg, sr_std, sr_min, sr_max,
                sr_elevado_n, sr_elevado_pct,
                margin_avg, margin_min,
            ])

    print(f"[EXPORT] Metrics: {path}")

    print(f"\n{'-'*100}")
    print(f"  {'No':<4} {'ToA_Teo':<10} {'Duty_RF':<9} {'Ocup_No':<9} {'Periodo_Nom':<13} {'Periodo_Real':<14} {'SR_avg':<10} {'SR_elevado'}")
    print(f"{'-'*100}")
    for dev_eui, stats in sorted(NODE_COUNTERS.items(), key=lambda x: x[1]['node_id']):
        node_id      = stats['node_id']
        toa_teo      = stats.get('toa_teorico_ms', 616)
        periodo_nom  = stats.get('periodo_nominal_s', 28)
        interval_list = stats.get('interval_real_list', [])
        periodo_real = round(sum(interval_list)/len(interval_list)/1000, 2) if interval_list else 0
        duty_rf      = round((toa_teo / (periodo_nom * 1000)) * 100, 2)
        ocup_no      = round((toa_teo / (periodo_real * 1000)) * 100, 2) if periodo_real else 0
        sr_list      = stats.get('sendreceive_list', [])
        sr_avg       = round(sum(sr_list)/len(sr_list), 0) if sr_list else 0
        sr_elev_pct  = round(sum(1 for s in sr_list if s > 2000) / len(sr_list) * 100, 1) if sr_list else 0
        print(f"  {str(node_id):<4} {toa_teo:<10} {duty_rf:<9}% {ocup_no:<9}% {periodo_nom:<13}s {periodo_real:<14}s {sr_avg:<10}ms {sr_elev_pct}%")
    print(f"{'-'*100}\n")


def _export_airtime_csv(path):
    session_end = dt.now()
    duration_s  = (session_end - SESSION_START).total_seconds()

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'node_id', 'dev_eui',
            'toa_teo_acumulado_s', 'duracao_sessao_s', 'utilizacao_canal_%',
            'duty_cycle_rf_medio_%', 'limite_legal_%', 'compliance'
        ])

        limite_legal = 1.0

        for dev_eui, stats in sorted(NODE_COUNTERS.items(), key=lambda x: x[1]['node_id']):
            node_id        = stats['node_id']
            toa_teo_acum_s = stats.get('toa_teo_acumulado_ms', 0) / 1000.0
            utilizacao     = (toa_teo_acum_s / duration_s) * 100 if duration_s > 0 else 0
            toa_teo        = stats.get('toa_teorico_ms', 616)
            periodo_nom    = stats.get('periodo_nominal_s', 28)
            duty_rf_medio  = (toa_teo / (periodo_nom * 1000)) * 100
            compliance     = "PASS" if duty_rf_medio <= limite_legal else "FAIL"

            writer.writerow([
                node_id, dev_eui,
                round(toa_teo_acum_s, 1), round(duration_s, 1), round(utilizacao, 2),
                round(duty_rf_medio, 2), limite_legal, compliance
            ])

    print(f"[EXPORT] Airtime: {path}")


def _export_summary_csv(path, temporal_cols=None):
    if not SESSION_DATA:
        return

    if temporal_cols is None:
        temporal_cols = detect_temporal_collisions(SESSION_DATA)

    session_end = dt.now()
    duration_s  = (session_end - SESSION_START).total_seconds()
    nodes       = set(f['node_id'] for f in SESSION_DATA if f['node_id'])
    n_nodes     = len(nodes)

    total_tx = 0
    for dev_eui, stats in NODE_COUNTERS.items():
        tx_current  = stats['last_fcnt'] + 1
        tx_previous = sum(s['tx_total'] for s in stats.get('sessions', []))
        total_tx   += tx_current + tx_previous

    total_rx        = len(SESSION_DATA)
    total_collisions = TOTAL_COLLISIONS
    pdr_global      = (total_rx / total_tx * 100) if total_tx > 0 else 0
    collision_rate  = (total_collisions / total_tx * 100) if total_tx > 0 else 0

    # FIX: filtro RSSI > -70dBm removido — excluía frames válidos (sensibilidade real ~-120dBm)
    all_frames_rssi = [f for f in SESSION_DATA if f.get('rssi') is not None]
    rssi_mean = sum(f['rssi'] for f in all_frames_rssi) / len(all_frames_rssi) if all_frames_rssi else 0
    snr_mean  = sum(f.get('snr', 0) for f in all_frames_rssi) / len(all_frames_rssi) if all_frames_rssi else 0
    margins   = [f['link_margin_db'] for f in SESSION_DATA if f.get('link_margin_db')]
    margin_mean = sum(margins) / len(margins) if margins else 0

    toa_teo_all = [f['toa_teorico_ms'] for f in SESSION_DATA if f.get('toa_teorico_ms')]
    toa_teo_avg = sum(toa_teo_all) / len(toa_teo_all) if toa_teo_all else 616

    # G calculado como soma por nó: G_total = sum(ToA_i / T_i)
    # Se payload v3.0 disponível (tx_attempt_count), usa método directo: G = attempts*ToA/duration
    G_real = 0
    g_method = 'intervalo'
    attempt_nodes = 0
    for dev_eui_g, stats_g in NODE_COUNTERS.items():
        toa_g = stats_g.get('toa_teorico_ms', 0)
        if not toa_g:
            continue
        last_attempt = stats_g.get('last_tx_attempt_count')
        if last_attempt and duration_s > 0:
            G_real += (last_attempt * toa_g / 1000) / duration_s
            attempt_nodes += 1
        else:
            intervals_g = [x for x in stats_g.get('interval_real_list', []) if 0 < x < 300000]
            if intervals_g:
                avg_interval_s = (sum(intervals_g) / len(intervals_g)) / 1000
                if avg_interval_s > 0:
                    G_real += (toa_g / 1000) / avg_interval_s

    if attempt_nodes == len(NODE_COUNTERS):
        g_method = 'tx_attempt_count (directo)'
    elif attempt_nodes > 0:
        g_method = f'misto ({attempt_nodes}/{len(NODE_COUNTERS)} nos com payload v3.0)'

    n_outliers = sum(
        len([x for x in stats.get('interval_real_list', []) if x >= 300000])
        for stats in NODE_COUNTERS.values()
    )
    if n_outliers:
        print(f"[G CALC] Filtrados {n_outliers} outliers (>=300000ms)")
    print(f"[G CALC] Metodo: {g_method} | G={G_real:.4f}")

    P_collision_theory    = (1 - math.exp(-2 * G_real)) * 100 if G_real > 0 else 0
    n_temporal_collisions = len(temporal_cols)
    temporal_col_rate     = (n_temporal_collisions / total_rx * 100) if total_rx > 0 else 0

    rx_sem_colisao      = sum(1 for f in SESSION_DATA
                              if f.get('collision_free', f.get('collisions_detected', 0) == 0))
    S_observado         = (rx_sem_colisao * toa_teo_avg / 1000) / duration_s if duration_s > 0 else 0
    S_pure_aloha_teoria = G_real * math.exp(-2 * G_real) if G_real > 0 else 0
    total_toa_teo_s       = sum(s.get('toa_teo_acumulado_ms', 0) for s in NODE_COUNTERS.values()) / 1000.0
    utilizacao_canal      = (total_toa_teo_s / duration_s) * 100 if duration_s > 0 else 0

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['parameter', 'value'])
        writer.writerows([
            ['session_start', SESSION_START.strftime('%Y-%m-%d %H:%M:%S')],
            ['session_end',   session_end.strftime('%Y-%m-%d %H:%M:%S')],
            ['duration_min',  round(duration_s / 60, 1)],
            [''],
            ['n_nodes', n_nodes],
            ['nodes',   ', '.join(f"No {n}" for n in sorted(nodes))],
            ['n_rejoins', len(JOIN_EVENTS)],
            [''],
            ['toa_teorico_avg_ms',       round(toa_teo_avg, 2)],
            ['G_calc_method',            g_method],
            ['traffic_load_G_real',      round(G_real, 4)],
            ['P_collision_theory_%',     round(P_collision_theory, 2)],
            ['utilizacao_canal_total_%', round(utilizacao_canal, 2)],
            [''],
            ['S_observado',              round(S_observado, 4)],
            ['S_pure_aloha_teoria',      round(S_pure_aloha_teoria, 4)],
            [''],
            ['total_tx',    total_tx],
            ['total_rx',    total_rx],
            ['total_lost',  total_collisions],
            ['pdr_uplink_%', round(pdr_global, 2)],
            [''],
            ['collision_rate_fcnt_%',     round(collision_rate, 2)],
            ['collisions_fcnt_gap',       total_collisions],
            ['collision_rate_temporal_%', round(temporal_col_rate, 2)],
            ['collisions_temporal',       n_temporal_collisions],
            ['pdr_plus_collision_%',      round(pdr_global + collision_rate, 2)],
            [''],
            ['rssi_mean_dBm',       round(rssi_mean, 2)],
            ['snr_mean_dB',         round(snr_mean, 2)],
            ['link_margin_mean_dB', round(margin_mean, 2)],
        ])

    print(f"[EXPORT] Summary: {path}")
    print(f"\n{'='*70}")
    print(f"  SESSION: {SESSION_START.strftime('%H:%M:%S')} -> {session_end.strftime('%H:%M:%S')} ({round(duration_s/60,1)} min)")
    print(f"  Nos:               {n_nodes}")
    print(f"  Total TX:          {total_tx}  |  RX: {total_rx}  |  Lost: {total_collisions}")
    print(f"  PDR:               {pdr_global:.1f}%")
    print(f"  Colisoes FCnt:     {total_collisions}  ({collision_rate:.1f}%)")
    print(f"  Colisoes Temporal: {n_temporal_collisions}  ({temporal_col_rate:.1f}%)")
    print(f"  Traffic Load G:    {G_real:.4f}")
    print(f"  P_colisao teorica: {P_collision_theory:.2f}%")
    print(f"  S_observado:       {S_observado:.4f}")
    print(f"  S_pureALOHA_teo:   {S_pure_aloha_teoria:.4f}  (G·e^-2G)")
    print(f"  Utilizacao Canal:  {utilizacao_canal:.2f}%")
    print(f"{'='*70}\n")


def _export_nodes_csv(path):
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'node_id', 'dev_eui', 'n_sessions',
            'sf', 'bw_khz', 'toa_teorico_ms', 'transacao_real_avg_ms',
            'tx_total', 'rx_total', 'collisions',
            'pdr_%', 'collision_rate_%', 'dl_pdr_%',
            'rssi_mean_dBm', 'snr_mean_dB', 'link_margin_mean_dB',
        ])

        for dev_eui, stats in sorted(NODE_COUNTERS.items(), key=lambda x: x[1]['node_id']):
            node_id     = stats['node_id']
            tx_current  = stats['last_fcnt'] + 1
            col_current = stats['collisions']
            tx_previous = sum(s['tx_total'] for s in stats.get('sessions', []))
            col_previous = sum(s['collisions'] for s in stats.get('sessions', []))
            tx_total    = tx_current + tx_previous
            collisions  = col_current + col_previous
            n_sessions  = stats.get('session_id', 1)

            node_frames = [f for f in SESSION_DATA if f['dev_eui'] == dev_eui]
            rx_total    = len(node_frames)
            pdr         = (rx_total / tx_total * 100) if tx_total > 0 else 0
            col_rate    = (collisions / tx_total * 100) if tx_total > 0 else 0

            # FIX: filtro RSSI > -70dBm removido
            all_frames = [f for f in node_frames if f.get('rssi') is not None]
            rssi_mean  = sum(f['rssi'] for f in all_frames) / len(all_frames) if all_frames else 0
            snr_mean   = sum(f.get('snr', 0) for f in all_frames) / len(all_frames) if all_frames else 0
            margins    = [f['link_margin_db'] for f in node_frames if f.get('link_margin_db')]
            margin_mean = sum(margins) / len(margins) if margins else 0

            transacao_list = stats.get('transacao_real_list', [])
            transacao_avg  = round(sum(transacao_list)/len(transacao_list), 1) if transacao_list else None

            dl_frames = [f for f in node_frames
                         if f.get('rx_expected') is not None and f.get('rx_success') is not None]
            if dl_frames:
                last_f  = dl_frames[-1]
                rx_exp  = last_f['rx_expected']
                rx_suc  = last_f['rx_success']
                dl_pdr  = round(rx_suc / (rx_exp + 1) * 100, 2) if rx_exp >= 0 else None
            else:
                dl_pdr = None

            writer.writerow([
                node_id, dev_eui, n_sessions,
                stats.get('sf'), stats.get('bw_khz'), stats.get('toa_teorico_ms'), transacao_avg,
                tx_total, rx_total, collisions,
                round(pdr, 2), round(col_rate, 2), dl_pdr,
                round(rssi_mean, 2), round(snr_mean, 2), round(margin_mean, 2),
            ])

    print(f"[EXPORT] Nodes: {path}")


def _export_temporal_collisions_csv(path, temporal_cols=None):
    if temporal_cols is None:
        temporal_cols = detect_temporal_collisions(SESSION_DATA)

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'timestamp', 'node_atual', 'fcnt_atual',
            'node_anterior', 'fcnt_anterior',
            'overlap_s', 'sf_atual', 'sf_anterior'
        ])
        for col in temporal_cols:
            writer.writerow([
                col['timestamp'], col['node_atual'], col['fcnt_atual'],
                col['node_anterior'], col['fcnt_anterior'],
                col['overlap_s'], col['sf_atual'], col['sf_anterior']
            ])

    print(f"[EXPORT] Temporal Collisions: {path} ({len(temporal_cols)} events)")


def _export_collisions_csv(path):
    collision_events = [f for f in SESSION_DATA if f.get('collisions_detected', 0) > 0]
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'node_id', 'session_id', 'f_cnt', 'collisions_detected'])
        for ev in collision_events:
            writer.writerow([
                ev['timestamp'], ev['node_id'], ev.get('session_id', 1),
                ev['f_cnt'], ev['collisions_detected'],
            ])
    print(f"[EXPORT] Collisions: {path} ({len(collision_events)} events)")


def _export_joins_csv(path):
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'dev_eui', 'event'])
        for ev in JOIN_EVENTS:
            writer.writerow([ev['timestamp'], ev['dev_eui'], ev['event']])
    print(f"[EXPORT] Joins: {path} ({len(JOIN_EVENTS)} events)")


def _export_sf_distribution_csv(path):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'node_id', 'f_cnt', 'session_id',
            'sf', 'toa_teorico_ms', 'rssi', 'snr', 'link_margin_db'
        ])
        writer.writeheader()
        for frame in SESSION_DATA:
            writer.writerow({
                'timestamp': frame.get('timestamp'),
                'node_id': frame.get('node_id'),
                'f_cnt': frame.get('f_cnt'),
                'session_id': frame.get('session_id'),
                'sf': frame.get('sf'),
                'toa_teorico_ms': frame.get('toa_teorico_ms'),
                'rssi': frame.get('rssi'),
                'snr': frame.get('snr'),
                'link_margin_db': frame.get('link_margin_db'),
            })

    print(f"[EXPORT] SF Distribution: {path}")

    print(f"\n{'-'*70}")
    print(f"  SF DISTRIBUTION SUMMARY:")
    print(f"{'-'*70}")
    for node_id in sorted(set(f.get('node_id') for f in SESSION_DATA if f.get('node_id'))):
        node_frames = [f for f in SESSION_DATA if f.get('node_id') == node_id]
        sf_counts = {}
        toa_by_sf = {}
        for frame in node_frames:
            sf = frame.get('sf')
            if sf:
                sf_counts[sf] = sf_counts.get(sf, 0) + 1
                toa_by_sf.setdefault(sf, [])
                if frame.get('toa_teorico_ms'):
                    toa_by_sf[sf].append(frame['toa_teorico_ms'])
        print(f"  No {node_id} ({len(node_frames)} frames):")
        for sf in sorted(sf_counts):
            pct     = sf_counts[sf] / len(node_frames) * 100
            avg_toa = sum(toa_by_sf[sf]) / len(toa_by_sf[sf]) if toa_by_sf.get(sf) else 0
            print(f"    SF{sf:2d}: {sf_counts[sf]:4d} frames ({pct:5.1f}%) | ToA avg: {avg_toa:7.1f}ms")
    print(f"{'-'*70}\n")


def _export_global_timestamps_csv(path):
    sorted_log = sorted(GLOBAL_TIMESTAMPS_LOG, key=lambda x: x['timestamp'])

    # --- passo 1: calcular delta_t_ms e observation para cada frame ---
    rows = []
    last_ts_dt = None
    potenciais_3s = 0

    for entry in sorted_log:
        try:
            curr_ts_dt = parse_ts(entry['timestamp'])
        except Exception:
            curr_ts_dt = dt.now()

        delta_t_ms  = None
        observation = "primeiro"

        if last_ts_dt is not None:
            delta_ms   = (curr_ts_dt - last_ts_dt).total_seconds() * 1000
            delta_t_ms = round(delta_ms, 1)
            if delta_t_ms < 3000:
                observation = "potencial_colisao"
                potenciais_3s += 1
            elif delta_t_ms < 60000:
                observation = "normal"
            else:
                observation = "gap"

        last_ts_dt = curr_ts_dt
        rows.append({
            'entry':       entry,
            'delta_t_ms':  delta_t_ms,
            'observation': observation,
            'potential_collision': False,
        })

    # --- passo 2: marcar colisões físicas (delta_rx < ToA_A) nos dois frames ---
    for i in range(1, len(rows)):
        toa_a  = rows[i-1]['entry'].get('toa_teorico_ms') or 616
        delta  = rows[i]['delta_t_ms']
        if delta is not None and delta < toa_a:
            rows[i-1]['potential_collision'] = True
            rows[i]['potential_collision']   = True

    pc_count = sum(1 for r in rows if r['potential_collision'])

    # --- escrita CSV ---
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'timestamp', 'node_id', 'fcnt', 'sf', 'toa_teorico_ms',
            'rssi', 'snr', 'delta_t_ms', 'observation',
            'delta_rx_ms', 'potential_collision',
        ])
        for r in rows:
            e = r['entry']
            writer.writerow([
                e['timestamp'], e['node_id'], e['fcnt'],
                e['sf'], e['toa_teorico_ms'],
                e['rssi'], e['snr'],
                r['delta_t_ms'] if r['delta_t_ms'] is not None else '',
                r['observation'],
                r['delta_t_ms'] if r['delta_t_ms'] is not None else '',
                r['potential_collision'],
            ])

    print(f"[EXPORT] Global Timestamps: {path} ({len(sorted_log)} frames)")
    print(f"  - delta_t < 3s (potenciais colisoes):    {potenciais_3s}")
    print(f"  - delta_rx < ToA (colisoes fisicas):      {pc_count}")


def input_listener():
    print("\n[SERVER] Commands: S=save Q=quit\n")
    while True:
        try:
            cmd = input().strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        key = cmd.split()[0].lower()
        if key == 's':
            print("\n[SERVER] Exporting...")
            export_session()
            raise SystemExit(0)
        elif key == 'q':
            print("\n[SERVER] Quit without saving...")
            raise SystemExit(0)


def shutdown_handler(sig, frame):
    print("\n[SERVER] CTRL+C -> exporting...")
    export_session()
    raise SystemExit(0)


if __name__ == '__main__':
    print("="*70)
    print("  Pure ALOHA Server v3.2 - Metricas para comparacao CW-ALOHA")
    print("  [NEW] S_observado, S_pure_aloha_teoria no summary")
    print("  [NEW] G_window + S_window (sliding 20 frames) no raw CSV")
    print("  [NEW] collision_free por frame no raw CSV")
    print("  [NEW] dl_pdr_% por no no nodes.csv")
    print("  [NEW] interval_std_s (era jitter_std_ms) em segundos no metrics.csv")
    print("  [NEW] collision_rate_fcnt_% / collision_rate_temporal_% no summary")
    print("="*70)
    print("  Commands: S=save Q=quit")
    print("="*70 + "\n")

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    t_input = threading.Thread(target=input_listener, daemon=True)
    t_input.start()

    app.run(host='0.0.0.0', port=5000, debug=False)
