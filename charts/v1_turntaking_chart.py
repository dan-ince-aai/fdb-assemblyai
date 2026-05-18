#!/usr/bin/env python3
"""FD-bench V1 Turn-taking latency chart (matches TML blog style)."""
import matplotlib.pyplot as plt

# (label, seconds, source). Lower is better.
DATA = [
    ("TML-interaction-small",            0.40, "TML blog"),
    ("Gemini-3.1-flash-live (minimal)",  0.57, "TML blog"),
    ("GPT-Realtime 1.5",                 0.59, "TML blog"),
    ("Gemini-3.1-flash-live (high)",     0.94, "TML blog"),
    ("GPT-Realtime 2.0 (minimal)",       1.18, "TML blog"),
    ("AssemblyAI Voice Agent",           1.62, "this run"),
    ("GPT-Realtime 2.0 (xhigh)",         1.63, "TML blog"),
    ("Qwen 3.5 OMNI plus realtime",      2.14, "TML blog"),
]

DATA.sort(key=lambda x: -x[1])  # slowest on top, so fastest is at bottom

labels = [l for l, _, _ in DATA]
times = [t for _, t, _ in DATA]

colors = []
for label, _, _ in DATA:
    if label == "AssemblyAI Voice Agent":
        colors.append("#FF6B35")
    elif "TML" in label:
        colors.append("#5B7DB1")
    else:
        colors.append("#B0B0B0")

fig, ax = plt.subplots(figsize=(10, 5.5))
bars = ax.barh(labels, times, color=colors, edgecolor="white", linewidth=1)

for bar, t in zip(bars, times):
    w = bar.get_width()
    ax.text(w + 0.04, bar.get_y() + bar.get_height() / 2,
            f"{t:.2f}s", va="center", ha="left",
            fontsize=10, color="#333", fontweight="bold")

ax.set_xlim(0, max(times) * 1.18)
ax.set_xlabel("Turn-taking latency (s) — lower is better", fontsize=11)
ax.set_title("Full-Duplex-Bench V1 — Turn-taking latency · Audio",
             fontsize=13, fontweight="bold", pad=15)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_color("#CCC")
ax.spines["bottom"].set_color("#CCC")
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", colors="#666")
ax.grid(axis="x", color="#EEE", linestyle="-", linewidth=0.5, zorder=0)
ax.set_axisbelow(True)

caption = ("Time from end of user turn to first agent audio (Silero VAD). "
           "AssemblyAI: 118 candor_turn_taking samples, mean. "
           "TML / FDB-paper numbers from public reports.")
fig.text(0.05, 0.01, caption, fontsize=8, color="#666", wrap=True)

fig.tight_layout(rect=[0, 0.04, 1, 1])
out_png = "/Users/danielince/Downloads/llm-gateway-streaming/fdb_v1_turntaking_chart.png"
fig.savefig(out_png, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Wrote {out_png}")
