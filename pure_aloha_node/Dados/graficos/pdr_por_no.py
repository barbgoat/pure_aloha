"""
Gráfico 5 — PDR por nó para as três sessões Pure ALOHA (T1/T2/T3).
Barras agrupadas por nó, com cor por sessão.
PDR = f_cnt_final / tx_attempt_count_final (última observação por nó).
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

BASE    = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

SESSIONS = {
    "T1 ($G=0{,}027$)": ("4_nodes_0265_vf",  "20260610_083021"),
    "T2 ($G=0{,}072$)": ("4_nodes_0724",     "20260609_130021"),
    "T3 ($G=0{,}121$)": ("4_nodes_1214_v1",  "20260609_090607"),
}
COLORS = ["#2166ac", "#f4a582", "#d6604d"]
NODES  = [1, 2, 3, 4]

pdr_data = {}
for sess_label, (folder, ts) in SESSIONS.items():
    pa = pd.read_csv(f"{BASE}/{folder}/pure_aloha_{ts}.csv", sep=";")
    pdrs = []
    for nid in NODES:
        sub = pa[pa["node_id"] == nid]
        last = sub.iloc[-1]
        pdr  = len(sub) / last["tx_attempt_count"] * 100
        pdr  = min(pdr, 100.0)
        pdrs.append(pdr)
    pdr_data[sess_label] = pdrs

x   = np.arange(len(NODES))
n   = len(SESSIONS)
w   = 0.22
offsets = np.linspace(-(n-1)*w/2, (n-1)*w/2, n)

fig, ax = plt.subplots(figsize=(7.5, 4.8))

for i, (label, pdrs) in enumerate(pdr_data.items()):
    bars = ax.bar(x + offsets[i], pdrs, w,
                  color=COLORS[i], alpha=0.88, label=label.replace("{,}", ","))
    for bar, val in zip(bars, pdrs):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.4,
                f"{val:.1f}%",
                ha="center", va="bottom", fontsize=7.5,
                color=COLORS[i], fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels([f"N{nid}" for nid in NODES], fontsize=11)
ax.set_ylabel("PDR (%)", fontsize=11)
ax.set_xlabel("Nó", fontsize=11)
ax.set_ylim(60, 104)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
ax.tick_params(labelsize=10)
ax.grid(axis="y", ls=":", lw=0.6, color="grey", alpha=0.5)
ax.legend(fontsize=9.5, framealpha=0.92, loc="lower left")

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "pdr_por_no.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(OUT_DIR, "pdr_por_no.png"), bbox_inches="tight", dpi=300)
plt.show()
print("Concluído.")
