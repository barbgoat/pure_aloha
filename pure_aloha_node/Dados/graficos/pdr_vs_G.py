import numpy as np
import matplotlib.pyplot as plt
import os

# ── Dados experimentais ───────────────────────────────────────────────────────
g_pure   = np.array([0.0265, 0.0724, 0.1214])
pdr_pure = np.array([0.962,  0.867,  0.688 ])

g_cw     = np.array([0.0264, 0.0715, 0.1215])
pdr_cw   = np.array([0.9786, 0.9372, 0.7834])

session_labels = ['T1', 'T2', 'T3']

# ── Curvas teóricas ───────────────────────────────────────────────────────────
G = np.linspace(0.001, 0.20, 600)
pdr_pure_th = np.exp(-2 * G)
pdr_cw_th   = np.exp(-G)

# ── Figura ────────────────────────────────────────────────────────────────────
BLUE = '#2166ac'
RED  = '#d6604d'

fig, ax = plt.subplots(figsize=(7.5, 4.8))

# Curvas teóricas
ax.plot(G, pdr_pure_th, color=BLUE, ls='--', lw=1.8, alpha=0.85,
        label=r'Pure ALOHA — teórico ($e^{-2G}$)')
ax.plot(G, pdr_cw_th,   color=RED,  ls='--', lw=1.8, alpha=0.85,
        label=r'CW-S-ALOHA — teórico ($e^{-G}$)')

# Pontos experimentais + linha de ligação suave
ax.plot(g_pure, pdr_pure, color=BLUE, lw=1.0, alpha=0.4)
ax.scatter(g_pure, pdr_pure, color=BLUE, marker='o', s=75, zorder=5,
           label='Pure ALOHA — experimental')

ax.plot(g_cw, pdr_cw, color=RED, lw=1.0, alpha=0.4)
ax.scatter(g_cw, pdr_cw, color=RED, marker='s', s=75, zorder=5,
           label='CW-S-ALOHA — experimental')

# ── Labels T1/T2/T3 nos pontos experimentais ─────────────────────────────────
# offset vertical: T1/T2 abaixo do ponto PA, T3 acima (evita sobreposição)
offsets = [(-0.003, -0.018), (-0.003, -0.018), (-0.003, +0.014)]
for i, lbl in enumerate(session_labels):
    dx, dy = offsets[i]
    ax.annotate(lbl,
                xy=(g_pure[i], pdr_pure[i]),
                xytext=(g_pure[i] + dx, pdr_pure[i] + dy),
                fontsize=8.5, color=BLUE, ha='center',
                fontweight='bold')
    ax.annotate(lbl,
                xy=(g_cw[i], pdr_cw[i]),
                xytext=(g_cw[i] + dx, pdr_cw[i] + dy),
                fontsize=8.5, color=RED, ha='center',
                fontweight='bold')

# ── Eixos e formatação ────────────────────────────────────────────────────────
ax.set_xlabel(r'Carga oferecida $G$', fontsize=11)
ax.set_ylabel('PDR', fontsize=11)
ax.set_xlim(0.0, 0.165)
ax.set_ylim(0.62, 1.02)
ax.yaxis.set_major_formatter(
    plt.FuncFormatter(lambda x, _: f'{x:.0%}')
)
ax.grid(True, ls=':', lw=0.6, color='grey', alpha=0.55)
ax.legend(fontsize=9.5, loc='lower left', framealpha=0.92)

plt.tight_layout()

BASE = os.path.dirname(os.path.abspath(__file__))
plt.savefig(os.path.join(BASE, 'pdr_vs_G.pdf'), bbox_inches='tight')
plt.savefig(os.path.join(BASE, 'pdr_vs_G.png'), bbox_inches='tight', dpi=300)
plt.show()
