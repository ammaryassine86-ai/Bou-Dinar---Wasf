"""Lot 3, follow-up: CodeCarbon 3 warned at every measurement that save_to_file « will be removed
in a future version » (128 warnings in the team's Windows run). Once it is removed, passing it
would make the tracker fail, and Wasf would quietly keep only the timing while CodeCarbon is
installed. Wasf now asks for « no output file » the way each version understands it."""
import sys
import types
import warnings
from typing import ClassVar

import pytest

from wasf.energy import EnergyMeter


class _Tracker:
    """Stands in for OfflineEmissionsTracker and records how it was set up."""
    made: ClassVar[list[dict]] = []

    def __init__(self, **options):
        _Tracker.made.append(options)
        self.final_emissions_data = types.SimpleNamespace(energy_consumed=0.000123)

    def start(self):
        pass

    def stop(self):
        return 0.000045            # kg of CO2


def _fake_codecarbon(monkeypatch, *, version3: bool) -> None:
    module = types.ModuleType("codecarbon")
    module.OfflineEmissionsTracker = _Tracker
    if version3:
        module.OutputMethod = object   # only its presence matters
    monkeypatch.setitem(sys.modules, "codecarbon", module)
    _Tracker.made.clear()


def test_codecarbon_3_is_asked_the_new_way(monkeypatch):
    _fake_codecarbon(monkeypatch, version3=True)
    with EnergyMeter("essai") as meter:
        pass
    options = _Tracker.made[-1]
    assert options["output_methods"] == [] and "save_to_file" not in options
    assert options["country_iso_code"] == "TUN"
    assert meter.result["outil"] == "codecarbon"
    assert meter.result["energie_kwh"] == 0.000123 and meter.result["co2_g"] == 0.045


def test_codecarbon_2_keeps_the_old_way(monkeypatch):
    _fake_codecarbon(monkeypatch, version3=False)
    with EnergyMeter("essai") as meter:
        pass
    options = _Tracker.made[-1]
    assert options["save_to_file"] is False and "output_methods" not in options
    assert meter.result["outil"] == "codecarbon"


def test_without_codecarbon_only_the_timing_is_kept(monkeypatch):
    monkeypatch.setitem(sys.modules, "codecarbon", None)    # the import fails
    with EnergyMeter("essai") as meter:
        pass
    assert meter.result["energie_kwh"] is None
    assert meter.result["outil"].startswith("chronomètre")


def test_the_real_codecarbon_measures_without_warning_or_file(tmp_path, monkeypatch):
    """Runs only where CodeCarbon is installed, as on the team's PC."""
    pytest.importorskip("codecarbon")
    monkeypatch.chdir(tmp_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with EnergyMeter("essai") as meter:
            sum(range(200_000))
    assert not [w for w in caught if "save_to_" in str(w.message)]
    assert meter.result["outil"] == "codecarbon"      # the settings were accepted
    assert not list(tmp_path.glob("*.csv"))           # no emissions file left behind
