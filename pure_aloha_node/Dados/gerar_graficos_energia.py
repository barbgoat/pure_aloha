import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os

BASE = os.path.dirname(os.path.abspath(__file__))

DEBUG_FILE = os.path.join(BASE, "10s_pure_deb",  "Administrator.csv")
LIGHT_FILE = os.path.join(BASE, "10s_pure_light", "Administrator_light.csv")
OUT_DEBUG  = os.path.join(BASE, "pure_debug_3ciclos.png")
OUT_LIGHT  = os.path.join(BASE, "pure_light_3ciclos.png")

Y_MIN, Y_MAX = 0, 125
FIG_W_CM     = 22
FIG_H_CM     = 7
DPI          = 300
LINE_COLOR   = "#1A3F6F"
LINE_W       = 0.5


def load(path):
    df = pd.read_csv(path, sep=";", header=0, engine="python")
    df = df.dropna(axis=1, how="all").iloc[:, :2]
    df.columns = ["t", "i"]
    df["t"] = pd.to_numeric(df["t"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["i"] = pd.to_numeric(df["i"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df = df.dropna()
    df["t"] = df["t"] - df["t"].iloc[0]   # t=0 no início do ficheiro
    df = df.iloc[::3].reset_index(drop=True)
    return df


def detect_tx_peaks(df, threshold=60, min_gap=5.0):
    """Devolve tempo do primeiro sample acima de threshold em cada burst TX."""
    peaks = []
    in_peak = False
    for _, row in df.iterrows():
        if row["i"] > threshold and not in_peak:
            if not peaks or (row["t"] - peaks[-1]) > min_gap:
                peaks.append(row["t"])
            in_peak = True
        elif row["i"] <= threshold:
            in_peak = False
    return peaks


def clip_to_cycles(df, peaks, n=2):
    """
    Recorta df para exactamente n ciclos completos (TX1 → TX1 + n*T)
    e devolve (df_clipped, Q [mAs], I_med [mA], T_real [s]).
    """
    if len(peaks) < 2:
        raise ValueError("São necessários pelo menos 2 picos TX para calcular o período.")

    T_real = peaks[1] - peaks[0]           # período medido entre TX1 e TX2
    t_end  = peaks[0] + n * T_real         # fim da janela de n ciclos (desde t=0)

    win = df[df["t"] <= t_end].copy()
    Q      = np.trapezoid(win["i"].values, win["t"].values)   # mAs
    I_med  = Q / t_end                                        # mA
    return win, Q, I_med, T_real


def make_annotations(peaks, rx_offset, rx_level, rx_label, idle_level, idle_label, tx_labels):
    anns = []

    for i, t in enumerate(peaks):
        lbl = tx_labels[i] if i < len(tx_labels) else tx_labels[-1]
        anns.append((lbl, (t, 113), (t + 1.65, 118), "left"))

    if peaks:
        t_rx = peaks[0] + rx_offset
        anns.append((rx_label, (t_rx, rx_level), (t_rx + 1.5, rx_level + 18), "left"))

    if peaks:
        t_mid = peaks[0] / 2
        anns.append((idle_label, (t_mid, idle_level), (t_mid, idle_level + 18), "center"))

    for i in range(len(peaks) - 1):
        t_mid = (peaks[i] + peaks[i + 1]) / 2
        anns.append((idle_label, (t_mid, idle_level), (t_mid, idle_level + 18), "center"))

    return anns


def plot(df, out_path, annotations, x_max=24):
    fig, ax = plt.subplots(figsize=(FIG_W_CM / 2.54, FIG_H_CM / 2.54))

    ax.plot(df["t"], df["i"], color=LINE_COLOR, linewidth=LINE_W, zorder=3)

    ax.set_xlim(0, x_max)
    ax.set_ylim(Y_MIN, Y_MAX)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(2))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(25))

    ax.set_xlabel("Tempo (s)", fontsize=11)
    ax.set_ylabel("Corrente (mA)", fontsize=11)
    ax.tick_params(labelsize=10)

    ax.grid(which="major", linestyle="-", linewidth=0.4, color="#d9d9d9", zorder=0)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    for (txt, xy, xytext, ha) in annotations:
        ax.annotate(
            txt, xy=xy, xytext=xytext,
            fontsize=8, ha=ha, va="center",
            arrowprops=dict(arrowstyle="-|>", color="#444444", lw=0.8, mutation_scale=8),
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#aaaaaa", lw=0.5, alpha=0.9),
            zorder=5,
        )

    for sp in ax.spines.values():
        sp.set_linewidth(0.6)
        sp.set_color("#aaaaaa")

    plt.tight_layout(pad=0.6)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Guardado: {out_path}")


# ── Carregar dados ──────────────────────────────────────────────────────────
df_debug = load(DEBUG_FILE)
df_light = load(LIGHT_FILE)

peaks_debug = detect_tx_peaks(df_debug)
peaks_light = detect_tx_peaks(df_light)
print(f"Debug TX peaks: {[round(p, 2) for p in peaks_debug]}")
print(f"Light TX peaks: {[round(p, 2) for p in peaks_light]}")

# ── Integrar sobre 2 ciclos completos (janela válida dos dados) ─────────────
_, Q_d, I_med_d, T_d = clip_to_cycles(df_debug, peaks_debug, n=2)
_, Q_l, I_med_l, T_l = clip_to_cycles(df_light, peaks_light, n=2)

print(f"\n=== DEBUG (2 ciclos integrados, T={T_d:.3f} s) ===")
print(f"  Q       = {Q_d:.2f} mAs")
print(f"  I_med   = {I_med_d:.2f} mA")
print(f"  Autonomia 1000 mAh = {1000/I_med_d:.0f} h")

print(f"\n=== LIGHT SLEEP (2 ciclos integrados, T={T_l:.3f} s) ===")
print(f"  Q       = {Q_l:.2f} mAs")
print(f"  I_med   = {I_med_l:.2f} mA")
print(f"  Autonomia 1000 mAh = {1000/I_med_l:.0f} h")

print(f"\nReducao: {(I_med_d - I_med_l)/I_med_d*100:.1f}%   Factor: {I_med_d/I_med_l:.2f}x")

# ── Anotações sobre todos os picos disponíveis (plot completo) ───────────────
ann_debug = make_annotations(
    peaks_debug,
    rx_offset=1.2, rx_level=57, rx_label="RX1/RX2\n(~54 mA)",
    idle_level=29, idle_label="Ativo\n(~29 mA)",
    tx_labels=["TX RF\n(~115 mA)", "TX RF\n(~116 mA)", "TX RF\n(~116 mA)"],
)
ann_light = make_annotations(
    peaks_light,
    rx_offset=1.35, rx_level=30, rx_label="RX1/RX2\n(~30 mA)",
    idle_level=2, idle_label="Sleep\n(~2 mA)",
    tx_labels=["TX RF\n(~117 mA)", "TX RF\n(~117 mA)", "TX RF\n(~117 mA)"],
)

# plot recebe df completo — mostra todos os dados disponíveis (~3 picos TX)
plot(df_debug, OUT_DEBUG, ann_debug)
plot(df_light, OUT_LIGHT, ann_light)
print("\nConcluído.")
