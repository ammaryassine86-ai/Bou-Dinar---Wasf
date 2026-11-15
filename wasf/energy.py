"""Energy measurement ("La planète" angle): CodeCarbon when installed, timing otherwise."""
from __future__ import annotations

import time

NOTE = ("Mesure locale uniquement : la consommation des serveurs d'un fournisseur d'IA "
        "distant n'est pas incluse.")


def tracker_options(label: str) -> dict:
    """CodeCarbon's settings: Tunisia's electricity, quiet, and no output file. CodeCarbon 3 says
    « no file » with output_methods=[] and warns that save_to_file will be removed, after which
    passing it would fail and leave only the timing; CodeCarbon 2 knows only save_to_file."""
    options = {"country_iso_code": "TUN", "log_level": "error",
               "project_name": f"wasf-{label}"}
    try:
        from codecarbon import OutputMethod  # noqa: F401  (CodeCarbon 3 and later)
        options["output_methods"] = []
    except ImportError:
        options["save_to_file"] = False
    return options


class EnergyMeter:
    def __init__(self, label: str):
        self.label = label
        self.result: dict = {}
        self._tracker = None

    def __enter__(self):
        self._t0 = time.perf_counter()
        self._c0 = time.process_time()
        try:
            from codecarbon import OfflineEmissionsTracker
            self._tracker = OfflineEmissionsTracker(**tracker_options(self.label))
            self._tracker.start()
        except Exception:  # not installed or unsupported platform: keep the timing only
            self._tracker = None
        return self

    def __exit__(self, *exc_info):
        result = {"etape": self.label,
                  "duree_s": round(time.perf_counter() - self._t0, 2),
                  "cpu_s": round(time.process_time() - self._c0, 2),
                  "outil": "chronomètre (installez codecarbon pour l'énergie)",
                  "energie_kwh": None, "co2_g": None, "remarque": NOTE}
        if self._tracker is not None:
            try:
                kg = self._tracker.stop() or 0.0
                data = getattr(self._tracker, "final_emissions_data", None)
                result.update(outil="codecarbon", co2_g=round(kg * 1000, 3),
                              energie_kwh=round(float(getattr(data, "energy_consumed", 0.0) or 0.0), 6))
            except Exception:
                pass
        self.result = result
        return False
