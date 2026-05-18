#!/usr/bin/env python3
"""Generate a TML-style FD-bench v1.5 Average (Audio) horizontal bar chart."""
import matplotlib.pyplot as plt

# (label, score, source)
DATA = [
    ("AssemblyAI Voice Agent",           82.7, "this run"),
    ("Nova Sonic",                       77.5, "FDB paper"),
    ("TML-interaction-small",            77.8, "TML blog"),
    ("Gemini Live",                      63.8, "FDB paper"),
    ("Gemini-3.1-flash-live (minimal)",  54.3, "TML blog"),
    ("Freeze-Omni",                      50.5, "FDB paper"),
    ("GPT-Realtime 1.5",                 48.3, "TML blog"),
    ("GPT-Realtime 2.0 (xhigh)",         47.8, "TML blog"),
    ("GPT-Realtime 2.0 (minimal)",       46.8, "TML blog"),
    ("Gemini-3.1-flash-live (high)",     45.5, "TML blog"),
    ("Qwen 3.5 OMNI plus realtime",      39.0, "TML blog"),
    ("GPT-4o Realtime",                  38.5, "FDB paper"),
    ("Moshi",                            20.5, "FDB paper"),
]

DATA.sort(key=lambda x: x[1])

labels = [f"{l}" for l, _, _ in DATA]
scores = [s for _, s, _ in DATA]
sources = [src for _, _, src in DATA]

colors = []
for label, _, _ in DATA:
    if label == "AssemblyAI Voice Agent":
        colors.append("#FF6B35")  # accent
    elif "TML" in label:
        colors.append("#5B7DB1")
    else:
        colors.append("#B0B0B0")

fig, ax = plt.subplots(figsize=(10, 7))
bars = ax.barh(labels, scores, color=colors, edgecolor="white", linewidth=1)

for bar, score in zip(bars, scores):
    w = bar.get_width()
    ax.text(w + 0.8, bar.get_y() + bar.get_height() / 2,
            f"{score:.1f}", va="center", ha="left",
            fontsize=10, color="#333", fontweight="bold")

ax.set_xlim(0, 90)
ax.set_xlabel("FD-bench V1.5 Average (Audio) — higher is better", fontsize=11)
ax.set_title("Full-Duplex-Bench V1.5 — behavior correctness across overlap scenarios",
             fontsize=13, fontweight="bold", pad=15)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_color("#CCC")
ax.spines["bottom"].set_color("#CCC")
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", colors="#666")
ax.grid(axis="x", color="#EEE", linestyle="-", linewidth=0.5, zorder=0)
ax.set_axisbelow(True)

caption = ("Aggregate of desired-behavior rate across 4 scenarios "
           "(user_interruption, user_backchannel, talking_to_other, background_speech). "
           "AssemblyAI: 498 samples, GPT-4o-2024-08-06 classifier (matches paper §2.3.1 category "
           "definitions; paper's full output_clean comparison not run). "
           "TML / FDB-paper numbers from public reports.")
fig.text(0.05, 0.01, caption, fontsize=8, color="#666", wrap=True)

fig.tight_layout(rect=[0, 0.04, 1, 1])
out_png = "/Users/danielince/Downloads/llm-gateway-streaming/fdb_v15_chart.png"
fig.savefig(out_png, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Wrote {out_png}")
