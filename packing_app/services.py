import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
from scipy.optimize import curve_fit, fsolve

matplotlib.use("Agg")
matplotlib.rcParams["text.usetex"] = False
matplotlib.rcParams["axes.formatter.use_mathtext"] = False

PSD_COLOR_PALETTE = ["#ef476f", "#f78c6b", "#06d6a0", "#118ab2", "#7f5539", "#8d99ae", "#8338ec", "#2a9d8f"]


@dataclass
class PSDData:
    name: str
    x: np.ndarray
    y: np.ndarray


def _normalize_col_name(name: str) -> str:
    return "".join(ch for ch in name.strip().lower() if ch.isalnum())


def _resolve_column(df: pd.DataFrame, accepted: set[str], label: str, role: str) -> str:
    col_map = {_normalize_col_name(col): col for col in df.columns}
    for candidate in accepted:
        if candidate in col_map:
            return col_map[candidate]
    raise ValueError(f"{label} is missing a valid {role} column. Found columns: {', '.join(map(str, df.columns))}")


def _read_psd(source: Any, label: str) -> PSDData:
    df = pd.read_csv(source)

    size_col = _resolve_column(df, {"size", "sizemm", "particlesizemm"}, label, "Size (mm)")
    acc_col = _resolve_column(
        df,
        {"accfromsmall", "accumfromsmall", "accumulationfromsmall", "cumulativefromsmall"},
        label,
        "Acc from small",
    )

    size = pd.to_numeric(df[size_col], errors="coerce").to_numpy(dtype=float)
    acc = pd.to_numeric(df[acc_col], errors="coerce").to_numpy(dtype=float)

    if size.size == 0:
        raise ValueError(f"{label} is empty.")
    if np.isnan(size).any() or np.isnan(acc).any() or np.isinf(size).any() or np.isinf(acc).any():
        raise ValueError(f"{label} contains non-numeric or invalid values in Size (mm)/Acc from small.")
    if np.any(size <= 0):
        raise ValueError(f"{label} Size (mm) values must be positive.")
    if np.any((acc < 0) | (acc > 100)):
        raise ValueError(f"{label} Acc from small values must be between 0 and 100.")

    order = np.argsort(size)
    size_sorted = size[order]
    acc_sorted = acc[order]

    if np.any(np.diff(acc_sorted) < -1e-6):
        raise ValueError(
            f"{label} Acc from small must be non-decreasing when Size (mm) is sorted from small to large."
        )
    if not np.isclose(acc_sorted[-1], 100.0, atol=1e-2):
        raise ValueError(
            f"{label} cumulative Acc from small at the largest Size (mm) must end at 100."
        )

    return PSDData(name=label, x=size_sorted, y=acc_sorted)


def _func(x_data: np.ndarray, x0: float, n: float) -> np.ndarray:
    x_data = np.maximum(np.asarray(x_data, dtype=float), 1e-12)
    x0 = max(float(x0), 1e-12)
    n = max(float(n), 1e-12)
    return 100.0 - (100.0 * np.exp(-((x_data / x0) ** n)))


def _fit_psd(name: str, x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    idx_50 = np.argmin(np.abs(y - 50.0))
    x0_est = float(max(x[idx_50], 1e-12))

    try:
        popt, _ = curve_fit(
            _func,
            x,
            y,
            p0=[x0_est, 1.0],
            bounds=([1e-12, 1e-12], [np.inf, np.inf]),
            maxfev=20000,
        )
    except Exception:
        popt = np.array([x0_est, 1.0], dtype=float)

    y_pred = _func(x, popt[0], popt[1])
    err = y_pred - y
    rmse = float(np.sqrt(np.mean(np.square(err))))
    var_y = float(np.var(y))
    rsq = 1.0 - (float(np.var(err)) / var_y) if var_y > 0 else 1.0

    return {
        "name": name,
        "x0": float(popt[0]),
        "n": float(popt[1]),
        "rmse": rmse,
        "rsq": rsq,
    }


def _interp_cdf(x: np.ndarray, y: np.ndarray, xq: np.ndarray) -> np.ndarray:
    return np.interp(xq, x, y, left=0.0, right=100.0)


def _build_psd_color_map(psd_names: list[str]) -> dict[str, str]:
    return {name: PSD_COLOR_PALETTE[idx % len(PSD_COLOR_PALETTE)] for idx, name in enumerate(psd_names)}


def _size_conditioned_psd_probs(
    psd_data: list[PSDData],
    volume_fractions: np.ndarray,
    size_queries: np.ndarray,
) -> np.ndarray:
    """Estimate P(PSD_k | size) from each PSD's differential CDF at queried sizes."""
    if not psd_data:
        return np.ones((len(size_queries), 1), dtype=float)

    vf = np.asarray(volume_fractions, dtype=float)
    if vf.size != len(psd_data) or np.any(vf < 0) or vf.sum() <= 0:
        vf = np.ones(len(psd_data), dtype=float)
    vf = vf / vf.sum()

    xmin = min(float(np.min(psd.x)) for psd in psd_data)
    xmax = max(float(np.max(psd.x)) for psd in psd_data)
    xgrid = np.logspace(np.log10(max(xmin, 1e-12)), np.log10(max(xmax, 1.01 * xmin)), 1000)

    per_psd_pdf = []
    for psd in psd_data:
        cdf = _interp_cdf(psd.x, psd.y, xgrid) / 100.0
        frac = np.diff(cdf, prepend=0.0)
        frac = np.clip(frac, 0.0, None)
        per_psd_pdf.append(frac)

    pdf_stack = np.vstack(per_psd_pdf)
    weighted = pdf_stack * vf[:, None]

    total = weighted.sum(axis=0)
    valid = total > 1e-15
    probs = np.zeros_like(weighted)
    probs[:, valid] = weighted[:, valid] / total[valid]
    if np.any(~valid):
        probs[:, ~valid] = vf[:, None]

    q = np.asarray(size_queries, dtype=float)
    q = np.clip(q, xgrid[0], xgrid[-1])
    idx = np.searchsorted(xgrid, q, side="left")
    idx = np.clip(idx, 0, len(xgrid) - 1)
    return probs[:, idx].T


def _plain_log_tick(value: float, _pos: float) -> str:
    if value <= 0:
        return ""
    if value >= 1000 or value < 0.01:
        return f"{value:.0e}"
    if value >= 1:
        return f"{value:.0f}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _mix_psd(psd_data: list[PSDData], masses: np.ndarray, densities: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    mass_fractions = masses / masses.sum()
    volume_fractions = (mass_fractions / densities)
    volume_fractions = volume_fractions / volume_fractions.sum()

    xmin = min(psd.x.min() for psd in psd_data)
    xmax = max(psd.x.max() for psd in psd_data)

    x_log = np.logspace(np.log10(xmin), np.log10(xmax), 200)
    stacked = np.vstack([_interp_cdf(psd.x, psd.y, x_log) for psd in psd_data])
    y_mix = np.average(stacked, axis=0, weights=volume_fractions)

    mix = pd.DataFrame({"Size": x_log, "Mix": y_mix})
    return mix, volume_fractions


def _prepare_for_packing(mix: pd.DataFrame, blended_beta: float) -> pd.DataFrame:
    data = mix.rename(columns={"Mix": "Acc from small"}).copy()
    data["Size"] = data["Size"].astype(float)
    data["Acc from small"] = data["Acc from small"].astype(float)

    ascending = data.sort_values("Size").reset_index(drop=True)
    ascending["Fraction"] = ascending["Acc from small"].diff().fillna(ascending["Acc from small"]) / 100.0

    if (ascending["Fraction"] < -1e-9).any():
        raise ValueError("Negative size fractions were computed. Ensure cumulative PSD is monotonic increasing.")

    ascending["Fraction"] = ascending["Fraction"].clip(lower=0.0)

    psd_ready = ascending.sort_values("Size", ascending=False).reset_index(drop=True)
    psd_ready.insert(0, "i", np.arange(1, len(psd_ready) + 1))
    psd_ready["Beta"] = float(blended_beta)
    return psd_ready


def _calculate_packing(data: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    n_classes = len(data)
    sizes = data["Size"].to_numpy(dtype=float)
    fractions = data["Fraction"].to_numpy(dtype=float)
    beta = data["Beta"].to_numpy(dtype=float)

    wall_sum = np.zeros(n_classes, dtype=float)
    loose_sum = np.zeros(n_classes, dtype=float)

    for i in range(n_classes):
        for j in range(i):
            ratio = sizes[i] / sizes[j]
            ratio = np.clip(ratio, 0.0, 1.0)
            wall = (1.0 - ratio) ** 1.3
            wall_sum[i] += wall * fractions[j]

    for i in range(n_classes):
        for j in range(i + 1, n_classes):
            ratio = sizes[i] / sizes[j]
            ratio = max(ratio, 1.0 + 1e-12)
            loose = 0.7 * (1.0 - (1.0 / ratio)) + 0.3 * (1.0 - (1.0 / ratio)) ** 12
            loose_sum[i] += loose * fractions[j]

    packing = beta / (1.0 - ((1.0 - beta) * wall_sum) - loose_sum)

    ready_for_pack = pd.DataFrame(
        {
            "i": data["i"].to_numpy(dtype=int),
            "Sum wall term in class i": wall_sum,
            "Sum loose term in class i": loose_sum,
            "Packing": packing,
        }
    ).set_index("i")

    final_packing = float(ready_for_pack["Packing"].min())
    return ready_for_pack, final_packing


def _solve_true_packing(y: np.ndarray, beta: np.ndarray, v_pack: float, k_value: float) -> float:
    def compact(phi: np.ndarray) -> float:
        phi_value = float(phi[0]) if np.ndim(phi) else float(phi)
        phi_value = max(phi_value, 1e-9)
        compact_class = (y / beta) / ((1.0 / phi_value) - (1.0 / v_pack))
        return float(np.sum(compact_class) - k_value)

    solution = fsolve(compact, 0.5)
    return float(solution[0])


def _fig_to_base64(fig: plt.Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_particle_packing_figure(
    data: pd.DataFrame,
    group_names: list[str],
    group_weights: np.ndarray,
    psd_color_map: dict[str, str],
    psd_data: list[PSDData],
) -> plt.Figure:
    viz_source = data[["Size", "Fraction"]].copy()
    viz_source = viz_source[viz_source["Fraction"] > 0].sort_values("Size").reset_index(drop=True)

    if viz_source.empty:
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.text(0.5, 0.5, "No positive fractions to visualize", ha="center", va="center")
        ax.set_axis_off()
        return fig

    n_bins = 20
    bin_edges = np.logspace(
        np.log10(viz_source["Size"].min()),
        np.log10(viz_source["Size"].max()),
        n_bins + 1,
    )

    viz_source["size_bin"] = pd.cut(
        viz_source["Size"],
        bins=bin_edges,
        labels=False,
        include_lowest=True,
    )
    viz_source["weighted_size"] = viz_source["Size"] * viz_source["Fraction"]

    binned = (
        viz_source.groupby("size_bin", observed=False)
        .agg(
            Fraction=("Fraction", "sum"),
            weighted_size=("weighted_size", "sum"),
        )
        .reset_index(drop=True)
    )
    binned = binned[binned["Fraction"] > 0].copy()
    binned["Size"] = binned["weighted_size"] / binned["Fraction"]
    binned = binned[["Size", "Fraction"]].sort_values("Size", ascending=False).reset_index(drop=True)

    log_sizes = np.log10(binned["Size"].to_numpy())
    if np.isclose(log_sizes.max(), log_sizes.min()):
        size_scale = np.ones_like(log_sizes)
    else:
        size_scale = (log_sizes - log_sizes.min()) / (log_sizes.max() - log_sizes.min())

    max_radius = 0.055
    min_radius = 0.008
    base_radii = min_radius + size_scale * (max_radius - min_radius)

    fractions = binned["Fraction"].to_numpy(dtype=float)
    fractions = fractions / fractions.sum()
    base_areas = np.pi * base_radii**2

    max_particles = 220
    count_scale = max_particles / np.sum(fractions / base_areas)
    counts = np.maximum(1, np.rint(count_scale * fractions / base_areas).astype(int))

    radii = base_radii

    if len(group_names) == 0:
        group_names = ["PSD_1"]

    size_group_probs = _size_conditioned_psd_probs(psd_data, group_weights, binned["Size"].to_numpy(dtype=float))
    if size_group_probs.shape[1] != len(group_names):
        weights = np.asarray(group_weights, dtype=float)
        if weights.size != len(group_names) or np.any(weights < 0) or np.sum(weights) <= 0:
            weights = np.ones(len(group_names), dtype=float)
        weights = weights / np.sum(weights)
        size_group_probs = np.tile(weights[None, :], (len(binned), 1))

    group_count_matrix = np.zeros((len(binned), len(group_names)), dtype=int)
    rng_groups = np.random.default_rng(42)
    for row_idx, (radius, count, size) in enumerate(zip(radii, counts, binned["Size"])):
        probs = size_group_probs[row_idx]
        probs = probs / probs.sum() if probs.sum() > 0 else np.ones(len(group_names), dtype=float) / len(group_names)
        group_count_matrix[row_idx] = rng_groups.multinomial(int(count), probs)

    unique_groups = list(dict.fromkeys(group_names))
    fig_height = 6.2
    fig, (ax_freq, ax) = plt.subplots(
        2,
        1,
        figsize=(10, fig_height),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.15], "hspace": 0.14},
    )

    if not np.any(group_count_matrix):
        ax.text(0.5, 0.5, "No particles to display", ha="center", va="center")
        ax.set_axis_off()
        ax_freq.set_axis_off()
        return fig

    material_color = {
        mat: psd_color_map.get(mat, PSD_COLOR_PALETTE[idx % len(PSD_COLOR_PALETTE)])
        for idx, mat in enumerate(unique_groups)
    }

    total_counts = group_count_matrix.sum(axis=1)
    size_values = binned["Size"].to_numpy(dtype=float)
    if len(size_values) == 1:
        bar_widths = np.array([size_values[0] * 0.25], dtype=float)
    else:
        log_sizes = np.log10(size_values)
        log_edges = np.empty(len(size_values) + 1, dtype=float)
        log_edges[1:-1] = 0.5 * (log_sizes[:-1] + log_sizes[1:])
        log_edges[0] = log_sizes[0] - 0.5 * (log_sizes[1] - log_sizes[0])
        log_edges[-1] = log_sizes[-1] + 0.5 * (log_sizes[-1] - log_sizes[-2])
        bar_widths = np.diff(10 ** log_edges) * 0.82

    ax_freq.bar(
        size_values,
        total_counts,
        width=bar_widths,
        color="#264653",
        edgecolor="#102022",
        alpha=0.86,
        align="center",
    )
    ax_freq.set_xscale("log")
    ax_freq.xaxis.set_major_formatter(FuncFormatter(_plain_log_tick))
    ax_freq.set_ylabel("Frequency")
    ax_freq.set_title("Particle Frequency by Size Bin")
    ax_freq.grid(True, which="both", linestyle="--", alpha=0.25)
    ax_freq.tick_params(axis="x", labelbottom=False)

    for size, count in zip(size_values, total_counts):
        ax_freq.text(size, count, str(int(count)), ha="center", va="bottom", fontsize=8, color="#102022")

    marker_sizes = np.interp(radii, (float(radii.min()), float(radii.max())), (280.0, 1200.0)) if len(radii) > 1 and radii.max() > radii.min() else np.full(len(radii), 520.0)
    y_offsets = np.linspace(-0.12, 0.12, num=max(len(unique_groups), 1))
    group_y = {material: y_offsets[idx] for idx, material in enumerate(unique_groups)}

    for row_idx, size in enumerate(size_values):
        for material_idx, material in enumerate(group_names):
            count = int(group_count_matrix[row_idx, material_idx])
            if count <= 0:
                continue

            ax.scatter(
                [size],
                [group_y.get(material, 0.0)],
                s=[marker_sizes[row_idx]],
                c=[material_color.get(material, "#999999")],
                edgecolors="black",
                linewidths=0.6,
                alpha=0.88,
                zorder=3,
            )
            ax.text(
                size,
                group_y.get(material, 0.0),
                str(count),
                ha="center",
                va="center",
                fontsize=8,
                color="#102022",
                zorder=4,
            )

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_plain_log_tick))
    ax.set_xlim(float(binned["Size"].min()) * 0.9, float(binned["Size"].max()) * 1.1)
    ax.set_ylim(-0.28, 0.28)
    ax.set_yticks([0.0])
    ax.set_yticklabels(["Particles"])
    ax.set_title("Normalized Particle Sketch")
    ax.set_xlabel("Size (mm)")
    ax.set_ylabel("Particle line")
    ax.grid(True, which="both", linestyle="--", alpha=0.25)

    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=material_color[m], markeredgecolor="black", markersize=8, linewidth=0)
        for m in unique_groups
    ]
    ax.legend(handles, unique_groups, title="PSD name legend", loc="upper left", fontsize=8)
    return fig


def _build_charts(
    psd_data: list[PSDData],
    fit_results: list[dict[str, float]],
    mix: pd.DataFrame,
    data: pd.DataFrame,
    ready_for_pack: pd.DataFrame,
    final_packing: float,
    group_names: list[str],
    group_weights: np.ndarray,
) -> dict[str, str]:
    psd_color_map = _build_psd_color_map([psd.name for psd in psd_data])

    fig1, ax1 = plt.subplots(figsize=(8, 5))
    for psd in psd_data:
        ax1.scatter(psd.x, psd.y, s=12, alpha=0.65, label=psd.name, color=psd_color_map[psd.name])
    ax1.plot(mix["Size"], mix["Mix"], color="#073b4c", linewidth=2.5, label="Mixed PSD")
    ax1.set_xscale("log")
    ax1.xaxis.set_major_formatter(FuncFormatter(_plain_log_tick))
    ax1.set_xlabel("Size (mm)")
    ax1.set_ylabel("Cumulative percentage")
    ax1.set_title("PSD(s) Plots")
    ax1.grid(True, which="both", linestyle="--", alpha=0.3)
    ax1.legend(loc="lower right")

    fig2, axes = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
    class_idx = ready_for_pack.index.to_numpy(dtype=int)

    axes[0].bar(class_idx, ready_for_pack["Sum wall term in class i"], color="#118ab2")
    axes[0].set_ylabel("Wall")
    axes[0].set_title("Wall Effect by Class")

    axes[1].bar(class_idx, ready_for_pack["Sum loose term in class i"], color="#06d6a0")
    axes[1].set_ylabel("Loose")
    axes[1].set_title("Loose Effect by Class")

    axes[2].plot(class_idx, ready_for_pack["Packing"], marker="o", color="#ef476f", linewidth=2)
    axes[2].axhline(final_packing, color="#073b4c", linestyle="--", linewidth=1.5)
    axes[2].set_xlabel("Class i")
    axes[2].set_ylabel("Packing")
    axes[2].set_title("Packing Density by Class")

    for axis in axes:
        axis.grid(True, linestyle="--", alpha=0.3)

    fig3 = _build_particle_packing_figure(
        data,
        group_names,
        group_weights,
        psd_color_map,
        psd_data,
    )

    fig4, axs4 = plt.subplots(
        max(1, (len(psd_data) + 1) // 2),
        min(len(psd_data), 2),
        figsize=(10, 4 * max(1, (len(psd_data) + 1) // 2)),
        squeeze=False,
    )
    flat_axes = axs4.flatten()
    for ax, psd, fit in zip(flat_axes, psd_data, fit_results):
        x_min = max(float(np.min(psd.x)), 1e-12)
        x_max = float(np.max(psd.x))
        if x_max > x_min:
            x_fit = np.logspace(np.log10(x_min), np.log10(x_max), 240)
        else:
            x_fit = np.linspace(x_min, x_min * 1.2, 100)

        y_fit = _func(x_fit, fit["x0"], fit["n"])

        psd_color = psd_color_map[psd.name]
        ax.scatter(psd.x, psd.y, s=13, alpha=0.7, color=psd_color, label="Data")
        ax.plot(x_fit, y_fit, color=psd_color, linewidth=2.0, linestyle="--", label="Fitted curve")
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(FuncFormatter(_plain_log_tick))
        ax.set_xlabel("Size (mm)")
        ax.set_ylabel("Cumulative percentage")
        ax.set_title(f"{fit['name']} | x0={fit['x0']:.3f}, n={fit['n']:.3f}, R²={fit['rsq']:.3f}")
        ax.grid(True, which="both", linestyle="--", alpha=0.3)
        ax.legend(loc="lower right", fontsize=8)

    # Hide any unused subplot axes
    for ax in flat_axes[len(psd_data):]:
        ax.set_visible(False)

    fig4.tight_layout()

    return {
        "mix_plot": _fig_to_base64(fig1),
        "effects_plot": _fig_to_base64(fig2),
        "particle_heatmap": _fig_to_base64(fig3),
        "fit_curves": _fig_to_base64(fig4),
    }


def run_calculation(
    sources: list[Any],
    masses: list[float],
    densities: list[float],
    betas: list[float],
    labels: list[str],
) -> dict[str, Any]:
    psd_data = [_read_psd(src, label) for src, label in zip(sources, labels)]

    masses_arr = np.array(masses, dtype=float)
    densities_arr = np.array(densities, dtype=float)
    betas_arr = np.array(betas, dtype=float)
    if masses_arr.sum() <= 0:
        raise ValueError("Active PSD mass fractions must sum to more than 0.")

    fit_results = [_fit_psd(psd.name, psd.x, psd.y) for psd in psd_data]
    mix, volume_fractions = _mix_psd(psd_data, masses_arr, densities_arr)
    normalized_masses = masses_arr / masses_arr.sum()

    input_summary = [
        {
            "name": labels[i],
            "mass_fraction": float(normalized_masses[i]),
            "rho": float(densities_arr[i]),
            "beta": float(betas_arr[i]),
        }
        for i in range(len(labels))
    ]

    blended_beta = float(np.average(betas_arr, weights=volume_fractions))
    data = _prepare_for_packing(mix, blended_beta)
    ready_for_pack, final_packing = _calculate_packing(data)

    y = data["Fraction"].to_numpy(dtype=float)
    beta_arr = data["Beta"].to_numpy(dtype=float)

    true_packing = {
        "no_compaction": final_packing,
        "k4": _solve_true_packing(y, beta_arr, final_packing, 4.0),
        "k6_7": _solve_true_packing(y, beta_arr, final_packing, 6.7),
        "k7": _solve_true_packing(y, beta_arr, final_packing, 7.0),
        "k9": _solve_true_packing(y, beta_arr, final_packing, 9.0),
    }

    charts = _build_charts(
        psd_data,
        fit_results,
        mix,
        data,
        ready_for_pack,
        final_packing,
        labels,
        volume_fractions,
    )

    return {
        "fit_results": fit_results,
        "mass_fractions": normalized_masses.tolist(),
        "volume_fractions": volume_fractions.tolist(),
        "input_summary": input_summary,
        "blended_beta": blended_beta,
        "final_packing": final_packing,
        "true_packing": true_packing,
        "charts": charts,
    }
