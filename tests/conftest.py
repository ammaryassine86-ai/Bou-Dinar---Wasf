import shutil

import pytest

from wasf import pipeline
from wasf.demo import make_demo
from wasf.pipeline import prepare
from wasf.providers import MockProvider


@pytest.fixture(scope="session")
def demo_files(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg n'est pas installé")
    return make_demo(tmp_path_factory.mktemp("demo"), "fr")


class StandIn(MockProvider):
    """Writes like the mock but is not a simulation: tests the wording a real model's track gets
    (the mock's own exports say « Simulation »)."""

    name = "essai"
    model = "doublure"


@pytest.fixture()
def real_path(demo_files, tmp_path, monkeypatch):
    """A demo project drafted by a stand-in for a real model."""
    monkeypatch.setattr(pipeline, "get_provider", lambda *args, **kwargs: StandIn())
    return prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "projet_essai",
                   log=lambda _msg: None)
