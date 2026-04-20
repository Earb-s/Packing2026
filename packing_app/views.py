from io import StringIO

from django.shortcuts import render

from .forms import PackingInputForm
from .services import run_calculation


def _psd_state_from_request(post_data, files) -> dict:
    if not post_data:
        return {
            "active_psd1": "1",
            "active_psd2": "1",
            "active_psd3": "1",
            "active_psd4": "1",
            "manual_psd1": "",
            "manual_psd2": "",
            "manual_psd3": "",
            "manual_psd4": "",
        }

    state = {
        "active_psd1": post_data.get("psd1_active", "1"),
        "active_psd2": post_data.get("psd2_active", "1"),
        "active_psd3": post_data.get("psd3_active", "1"),
        "active_psd4": post_data.get("psd4_active", "1"),
        "manual_psd1": post_data.get("manual_psd1", ""),
        "manual_psd2": post_data.get("manual_psd2", ""),
        "manual_psd3": post_data.get("manual_psd3", ""),
        "manual_psd4": post_data.get("manual_psd4", ""),
    }

    # Persist uploaded files as inline CSV text for immediate re-calculation without re-upload.
    for i in range(1, 5):
        upload = files.get(f"psd{i}") if files else None
        if upload:
            raw = upload.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            state[f"manual_psd{i}"] = text
            upload.seek(0)

    return state


def _resolve_sources(files, post_data, active_indices: list) -> tuple[list, list]:
    resolved = []
    used_indices = []

    for index in active_indices:
        upload = files.get(f"psd{index + 1}")
        if upload:
            resolved.append(upload)
            used_indices.append(index)
            continue

        manual_csv = post_data.get(f"manual_psd{index + 1}", "").strip()
        if manual_csv:
            resolved.append(StringIO(manual_csv))
            used_indices.append(index)
            continue

        # Active but empty source is skipped. Only provided PSDs are used.
        continue

    if not resolved:
        raise ValueError("No PSD input found. Please upload at least one PSD file or use manual input.")

    return resolved, used_indices


def index(request):
    result = None
    psd_state = _psd_state_from_request(None, None)

    if request.method == "POST":
        form = PackingInputForm(request.POST, request.FILES)
        psd_state = _psd_state_from_request(request.POST, request.FILES)
        if form.is_valid():
            try:
                active_indices = [
                    i for i in range(4)
                    if request.POST.get(f"psd{i + 1}_active", "1") == "1"
                ]
                if not active_indices:
                    form.add_error(None, "All PSD files have been removed. Please restore at least one PSD to run the simulation.")
                else:
                    sources, used_indices = _resolve_sources(request.FILES, request.POST, active_indices)
                    masses = [form.cleaned_data[f"m{i + 1}"] for i in used_indices]
                    densities = [form.cleaned_data[f"rho{i + 1}"] for i in used_indices]
                    betas = [form.cleaned_data[f"beta{i + 1}"] for i in used_indices]
                    labels = [
                        (form.cleaned_data.get(f"material_name{i + 1}") or "").strip() or f"PSD_{i + 1}"
                        for i in used_indices
                    ]
                    result = run_calculation(sources, masses, densities, betas, labels)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = PackingInputForm()

    return render(request, "index.html", {"form": form, "result": result, **psd_state})


def theory(request):
    return render(request, "theory.html")


def manual_psd_window(request):
    slot = request.GET.get("slot", "psd1")
    if slot not in {"psd1", "psd2", "psd3", "psd4"}:
        slot = "psd1"
    mode = request.GET.get("mode", "accfromsmall")
    if mode not in {"rosinrammler", "accfromsmall", "frequency"}:
        mode = "accfromsmall"
    return render(request, "manual_psd_window.html", {"slot": slot, "mode": mode})
