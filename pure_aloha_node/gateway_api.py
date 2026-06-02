#!/usr/bin/env python3
"""
gateway_api.py — Integração gRPC com ChirpStack v4
Pure ALOHA Server

Migrado de REST (requests + porta 8090) para gRPC (porta 8080).
Ver notas de migração no server.py.
"""

import grpc
from chirpstack_api import api

# ── Credenciais ChirpStack actual ──────────────────────────────────────────
CHIRPSTACK_HOST = "192.168.168.175"
CHIRPSTACK_PORT = 8080
APP_ID          = "7bbd73af-7f65-4c7d-bfc8-3ea7e4d12e33"
API_KEY         = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJjaGlycHN0YWNrIiwiaXNzIjoiY2hpcnBzdGFjayIsInN1YiI6IjI4NmM5MzU3LTBhY2MtNGRmZi04NmE2LTAzMjBlODMwZTRkZiIsInR5cCI6ImtleSJ9.uVA3cGrxiDnf24fDDDqb1paVLWWuIPLH3xHTs5QXOJA"
# ──────────────────────────────────────────────────────────────────────────


def _channel():
    return grpc.insecure_channel(f"{CHIRPSTACK_HOST}:{CHIRPSTACK_PORT}")


def _meta():
    return [("authorization", f"Bearer {API_KEY}")]


def flush_dev_nonces(dev_eui: str) -> bool:
    """Limpa os dev-nonces OTAA de um dispositivo (permite rejoin limpo)."""
    try:
        client = api.DeviceServiceStub(_channel())
        req = api.FlushDevNoncesRequest()
        req.dev_eui = dev_eui
        client.FlushDevNonces(req, metadata=_meta())
        print(f"[FLUSH] {dev_eui[-8:]} nonces cleared (gRPC)")
        return True
    except Exception as e:
        print(f"[FLUSH] {dev_eui[-8:]} error: {e}")
        return False


def flush_downlink_queue(dev_eui: str) -> bool:
    """Limpa a fila de downlinks pendentes de um dispositivo."""
    try:
        client = api.DeviceServiceStub(_channel())
        req = api.FlushDeviceQueueRequest()
        req.dev_eui = dev_eui
        client.FlushDeviceQueue(req, metadata=_meta())
        print(f"[FLUSH] {dev_eui[-8:]} downlink queue cleared (gRPC)")
        return True
    except Exception as e:
        print(f"[FLUSH] {dev_eui[-8:]} queue error: {e}")
        return False
