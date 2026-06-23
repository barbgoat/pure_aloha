"""
Gráfico 4 — Distribuição de sendreceive_ms por nó na sessão T2 (0724).
Violin plot com box interior e pontos individuais decimados.
Mostra a distribuição bimodal de N1 (retorno em RX1 vs espera em RX2).
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

PATH    = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha\4_nodes_0724\pure_aloha_20260609_130021.csv"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

BLUE   = "#2166ac"
COLORS = ["#2166ac", "#4dac26", "#d01c8b", "#f1a340"]  # N1-N4

df = pd.read_csv(PATH, sep=";")
df = df.dropna(subset=["sendreceive_ms"])
df["sendreceive_ms"] = pd.to_numeric(df["sendreceive_ms"], errors="coerce")
df = df.dropna(subset=["sendreceive_ms"])

nodes   = sorted(df["node_id"].unique())
labels  = [f"N{nid}" for nid in nodes]
data    = [df[df["node_id"] == nid]["sendreceive_ms"].values for nid in nodes]

fig, ax = plt.subplots(figsize=(7.5, 4.8))

parts = ax.violinplot(data, positions=range(1, len(nodes)+1),
                      showmedians=False, showextrema=False, widths=0.6)

for i, (pc, col) in enumerate(zip(parts["bodies"], COLORS)):
    pc.set_facecolor(col)
    pc.set_alpha(0.35)
    pc.set_edgecolor(col)
    pc.set_linewidth(1.2)

# Box interior
bp = ax.boxplot(data, positions=range(1, len(nodes)+1),
                widths=0.12, patch_artist=True,
                manage_ticks=False,
                boxprops    = dict(facecolor="white", color="#555555", linewidth=1.0),
                medianprops = dict(color="#c0392b", linewidth=2.0),
                whiskerprops= dict(color="#555555", linewidth=0.8),
                capprops    = dict(color="#555555", linewidth=1.0),
                flierprops  = dict(marker=".", markersize=2, color="#aaaaaa", alpha=0.3))

# Pontos individuais decimados (1:4)
rng = np.random.default_rng(42)
for i, (nid, col) in enumerate(zip(nodes, COLORS)):
    vals = data[i]
    decimated = vals[::4]
    jitter = rng.uniform(-0.08, 0.08, size=len(decimated))
    ax.scatter(np.full(len(decimated), i+1) + jitter, decimated,
               s=3, color=col, alpha=0.25, zorder=2)

# Linhas de referência RX1 e RX2
ax.axhline(1300, color="#888888", ls="--", lw=0.9, alpha=0.7)
ax.axhline(2000, color="#888888", ls=":",  lw=0.9, alpha=0.7)
ax.text(len(nodes) + 0.55, 1300, "RX1\n(~1300 ms)", va="center",
        fontsize=8, color="#666666")
ax.text(len(nodes) + 0.55, 2000, "RX2\n(~2000 ms)", va="center",
        fontsize=8, color="#666666")

# Estatísticas N1 (anotação)
n1_std = df[df["node_id"]==nodes[0]]["sendreceive_ms"].std()
ax.text(1, df[df["node_id"]==nodes[0]]["sendreceive_ms"].max() + 30,
        f"σ = {n1_std:.0f} ms", ha="center", fontsize=8.5,
        color=COLORS[0], fontweight="bold")

ax.set_xticks(range(1, len(nodes)+1))
ax.set_xticklabels(labels, fontsize=11)
ax.set_ylabel("sendreceive() — duração (ms)", fontsize=11)
ax.set_xlabel("Nó (sessão T2)", fontsize=11)
ax.set_xlim(0.4, len(nodes) + 1.2)
ax.tick_params(labelsize=10)
ax.grid(axis="y", ls=":", lw=0.6, color="grey", alpha=0.5)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "sendreceive_violin.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(OUT_DIR, "sendreceive_violin.png"), bbox_inches="tight", dpi=300)
plt.show()
print("Concluído.")
