"""
PDR vs carga oferecida G — box plots por janela temporal (Pure ALOHA).

Para cada sessão (T1/T2/T3) divide o tempo em janelas de WINDOW_MIN minutos.
Em cada janela e para cada nó calcula:
    PDR = frames_recebidos / tentativas_TX
onde tentativas_TX = max(tx_attempt_count) - min(tx_attempt_count) + 1 na janela.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Configuração ─────────────────────────────────────────────────────────────
BASE_DATA = r"c:\Users\Eduardo Barbosa\Documents\Arduino\pure_aloha\pure_aloha_node\teste_pure_aloha"
OUT_DIR   = os.path.dirname(os.path.abspath(__file__))

SESSIONS = {
    "T1": {
        "path": os.path.join(BASE_DATA, "4_nodes_0265_vf", "pure_aloha_20260610_083021.csv"),
        "G": 0.0265,
    },
    "T2": {
        "path": os.path.join(BASE_DATA, "4_nodes_0724",    "pure_aloha_20260609_130021.csv"),
        "G": 0.0724,
    },
    "T3": {
        "path": os.path.join(BASE_DATA, "4_nodes_1214_v1", "pure_aloha_20260609_090607.csv"),
        "G": 0.1214,
    },
}

WINDOW_MIN = 10   # tamanho da janela temporal (minutos)
MIN_FRAMES = 5    # mínimo de frames por janela/nó para incluir (evita janelas incompletas)

BLUE = "#2166ac"

# ── Carrega e calcula PDR por janela ─────────────────────────────────────────
def pdr_windows(path, window_min, min_frames):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    t0 = df["timestamp"].iloc[0]
    df["elapsed_min"] = (df["timestamp"] - t0).dt.total_seconds() / 60

    pdr_vals = []
    nodes    = sorted(df["node_id"].unique())
    n_windows = int(df["elapsed_min"].max() // window_min)

    for w in range(n_windows):
        t_lo = w * window_min
        t_hi = t_lo + window_min
        win  = df[(df["elapsed_min"] >= t_lo) & (df["elapsed_min"] < t_hi)]
        for nid in nodes:
            sub = win[win["node_id"] == nid].dropna(subset=["tx_attempt_count"])
            if len(sub) < min_frames:
                continue
            received = len(sub)
            attempts = int(sub["tx_attempt_count"].max() - sub["tx_attempt_count"].min()) + 1
            if attempts < min_frames:
                continue
            pdr_vals.append(min(received / attempts, 1.0))  # cap a 1.0 (join no início)

    return np.array(pdr_vals)

data = {}
for name, cfg in SESSIONS.items():
    vals = pdr_windows(cfg["path"], WINDOW_MIN, MIN_FRAMES)
    data[name] = {"G": cfg["G"], "pdr": vals}
    print(f"{name}: G={cfg['G']:.4f}, n_janelas={len(vals)}, "
          f"mediana={np.median(vals)*100:.1f}%, IQR=[{np.percentile(vals,25)*100:.1f}, {np.percentile(vals,75)*100:.1f}]%")

# ── Curva teórica Pure ALOHA ─────────────────────────────────────────────────
G_th  = np.linspace(0.001, 0.16, 600)
PDR_th = np.exp(-2 * G_th)

# ── Figura ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7.5, 4.8))

# Curva teórica
ax.plot(G_th, PDR_th, color=BLUE, ls="--", lw=1.8, alpha=0.75,
        label=r"Pure ALOHA — teórico ($e^{-2G}$)", zorder=2)

# Box plots
BOX_W = 0.006   # largura de cada box em unidades de G
positions = [cfg["G"] for cfg in SESSIONS.values()]
box_data  = [data[n]["pdr"] for n in SESSIONS]

bp = ax.boxplot(
    box_data,
    positions=positions,
    widths=BOX_W,
    patch_artist=True,
    notch=False,
    manage_ticks=False,
    zorder=4,
    boxprops    = dict(facecolor=(*[c/255 for c in (33, 102, 172)], 0.20),
                       color=BLUE, linewidth=1.2),
    medianprops = dict(color="#c0392b", linewidth=2.0),
    whiskerprops= dict(color=BLUE, linewidth=1.0, linestyle="-"),
    capprops    = dict(color=BLUE, linewidth=1.2),
    flierprops  = dict(marker=".", markersize=3, color=BLUE, alpha=0.4),
)

# Linha pelos pontos médios (média de cada sessão)
means   = [np.mean(data[n]["pdr"]) for n in SESSIONS]
g_vals  = [data[n]["G"] for n in SESSIONS]
ax.plot(g_vals, means, color=BLUE, marker="o", ms=6, lw=1.4,
        zorder=5, label="Pure ALOHA — média experimental")

# Labels T1/T2/T3 acima de cada box
offsets_y = [0.022, 0.022, -0.028]   # T1/T2 acima, T3 abaixo (evita saída do eixo)
for i, (name, cfg) in enumerate(SESSIONS.items()):
    median = np.median(data[name]["pdr"])
    ax.text(cfg["G"], median + offsets_y[i], name,
            ha="center", va="center", fontsize=8.5,
            color=BLUE, fontweight="bold")

# ── Legenda ──────────────────────────────────────────────────────────────────
median_patch = mpatches.Patch(color="#c0392b", label="Mediana por sessão")
handles, labels = ax.get_legend_handles_labels()
ax.legend(handles + [median_patch], labels + ["Mediana por sessão"],
          fontsize=9, loc="lower left", framealpha=0.92)

# ── Eixos e formatação ────────────────────────────────────────────────────────
ax.set_xlabel(r"Carga oferecida $G$", fontsize=11)
ax.set_ylabel("PDR", fontsize=11)
ax.set_xlim(0.0, 0.155)
ax.set_ylim(0.58, 1.04)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
ax.xaxis.set_major_locator(plt.MultipleLocator(0.02))
ax.grid(True, ls=":", lw=0.6, color="grey", alpha=0.5)
ax.tick_params(labelsize=10)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "pdr_boxplot.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(OUT_DIR, "pdr_boxplot.png"), bbox_inches="tight", dpi=300)
plt.show()
print("Concluído.")
