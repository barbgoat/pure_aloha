"""
Gráfico 7 — Calibração de relógio: offset_raw_ms normalizado vs tempo (sessão T1).
Mostra a deriva linear do oscilador de cada nó e os resíduos em torno do modelo.
offset_raw = ts_gateway_epoch_ms − node_millis − ToA
Normalizado subtraindo o valor inicial por nó.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

PATH    = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha\4_nodes_0265_vf\pure_aloha_20260610_083021.csv"
CALIB   = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha\4_nodes_0265_vf\clock_calibration_20260610_083021.csv"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

COLORS = ["#2166ac", "#4dac26", "#d01c8b", "#f1a340"]
NODES  = [1, 2, 3, 4]
TOA_MS = 97.536

df = pd.read_csv(PATH, sep=";")
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df["node_millis"] = pd.to_numeric(df["node_millis"], errors="coerce")
df["offset_raw_ms"] = pd.to_numeric(df["offset_raw_ms"], errors="coerce")
df = df.dropna(subset=["node_millis", "offset_raw_ms"])

calib = pd.read_csv(CALIB, sep=";")

fig, ax = plt.subplots(figsize=(8.5, 4.8))

for i, (nid, col) in enumerate(zip(NODES, COLORS)):
    sub = df[df["node_id"] == nid].sort_values("node_millis").copy()
    if sub.empty:
        continue

    x_s  = sub["node_millis"].values / 1000          # segundos de uptime
    y_ms = sub["offset_raw_ms"].values
    y_norm = y_ms - y_ms[0]                           # desvio desde o arranque

    # Regressão linear (deriva)
    slope, intercept = np.polyfit(x_s, y_norm, 1)
    drift_ppm = -slope * 1e3                          # slope em ms/s → ppm
    x_fit = np.array([x_s[0], x_s[-1]])
    y_fit = slope * x_fit + intercept

    # Dispersão (1:6 pontos para não saturar)
    ax.scatter(x_s[::6] / 60, y_norm[::6],
               s=4, color=col, alpha=0.25, zorder=2)

    # Linha de ajuste linear
    ax.plot(x_fit / 60, y_fit, color=col, lw=1.8, zorder=4,
            label=f"N{nid} — {drift_ppm:.1f} ppm")

# Calib residual annotation
calib_vals = calib.set_index("node_id")
for i, (nid, col) in enumerate(zip(NODES, COLORS)):
    if nid in calib_vals.index:
        res = calib_vals.loc[nid, "residual_std_ms"]
        row = df[df["node_id"]==nid].sort_values("node_millis").iloc[-1]
        x_end = row["node_millis"] / 1000 / 60
        y_end = (row["offset_raw_ms"] - df[df["node_id"]==nid].sort_values("node_millis").iloc[0]["offset_raw_ms"])
        ax.annotate(f"σ={res:.0f} ms",
                    xy=(x_end, y_end),
                    xytext=(x_end - 20, y_end + 12 * (1 if i % 2 == 0 else -1)),
                    fontsize=7.5, color=col,
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.7))

ax.set_xlabel("Tempo de funcionamento do nó (min)", fontsize=11)
ax.set_ylabel("Desvio de offset_raw desde o arranque (ms)", fontsize=11)
ax.tick_params(labelsize=10)
ax.grid(ls=":", lw=0.6, color="grey", alpha=0.5)
ax.legend(fontsize=9.5, framealpha=0.92, title="Nó — deriva estimada", title_fontsize=9)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "clock_calibration.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(OUT_DIR, "clock_calibration.png"), bbox_inches="tight", dpi=300)
plt.show()
print("Concluído.")
