"""
Gráfico 3 — Perdas fCnt gap vs colisões temporais por sessão (Pure ALOHA).
Escala log no eixo Y para tornar visível a diferença de ordens de grandeza.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

BASE    = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

SESSIONS = {
    "T1": ("4_nodes_0265_vf",  "20260610_083021"),
    "T2": ("4_nodes_0724",     "20260609_130021"),
    "T3": ("4_nodes_1214_v1",  "20260609_090607"),
}

BLUE = "#2166ac"
RED  = "#d6604d"

fcnt_losses    = {}
temporal_count = {}
total_tx       = {}

for name, (folder, ts) in SESSIONS.items():
    pa = pd.read_csv(f"{BASE}/{folder}/pure_aloha_{ts}.csv", sep=";")
    losses, tx_tot = 0, 0
    for nid in pa["node_id"].unique():
        sub = pa[pa["node_id"] == nid]
        tx  = int(sub["tx_attempt_count"].max())
        rx  = len(sub)
        losses  += tx - rx
        tx_tot  += tx
    fcnt_losses[name]    = losses
    total_tx[name]       = tx_tot

    tc = pd.read_csv(f"{BASE}/{folder}/temporal_collisions_{ts}.csv", sep=";")
    temporal_count[name] = len(tc)

sessions = list(SESSIONS.keys())
fl_vals  = [fcnt_losses[s]    for s in sessions]
tc_vals  = [temporal_count[s] for s in sessions]
tx_vals  = [total_tx[s]       for s in sessions]
fl_rate  = [l / t * 100 for l, t in zip(fl_vals, tx_vals)]
tc_rate  = [c / t * 100 for c, t in zip(tc_vals, tx_vals)]

x = np.arange(len(sessions))
w = 0.35

fig, ax = plt.subplots(figsize=(7.5, 4.8))

bars_fl = ax.bar(x - w/2, fl_vals, w, color=BLUE, alpha=0.85,
                 label="Perdas por fCnt gap")
# Para log scale, temporal=0 em T2 → usar placeholder mínimo para visualização
tc_plot = [max(v, 0.4) for v in tc_vals]
bars_tc = ax.bar(x + w/2, tc_plot, w, color=RED, alpha=0.85,
                 label="Colisões temporais detectadas")

ax.set_yscale("log")
ax.set_ylim(0.3, 8000)
ax.set_xticks(x)
ax.set_xticklabels(sessions, fontsize=11)
ax.set_ylabel("Número de eventos (escala log)", fontsize=11)
ax.tick_params(labelsize=10)
ax.grid(axis="y", ls=":", lw=0.6, color="grey", alpha=0.5)
ax.legend(fontsize=9.5, framealpha=0.92)

# Etiquetas nas barras fCnt
for bar, val, rate in zip(bars_fl, fl_vals, fl_rate):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() * 1.18,
            f"{val}\n({rate:.1f}%)",
            ha="center", va="bottom", fontsize=8.5,
            color=BLUE, fontweight="bold")

# Etiquetas nas barras temporais
for bar, val, rate in zip(bars_tc, tc_vals, tc_rate):
    label = "0\n(0,00%)" if val == 0 else f"{val}\n({rate:.2f}%)"
    ypos  = 0.55 if val == 0 else bar.get_height() * 1.18
    ax.text(bar.get_x() + bar.get_width() / 2,
            ypos, label,
            ha="center", va="bottom", fontsize=8.5,
            color=RED, fontweight="bold")

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "colisoes_bar.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(OUT_DIR, "colisoes_bar.png"), bbox_inches="tight", dpi=300)
plt.show()
print("Concluído.")
