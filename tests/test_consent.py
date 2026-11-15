"""The producer's permission (audit of 15/11/2026, finding 1): only YAML's true counts as a yes,
and the agreement's reference is required. « non » used to pass, since in Python every non-empty
text counts as true."""
import pytest

from wasf.intent import IntentError, RightsError, load_intent

REFERENCE = "  reference: Accord écrit du producteur, courriel du 13/11/2026\n"


def _intent(tmp_path, rights: str):
    path = tmp_path / "intention.yaml"
    path.write_text("film: Test\n" + rights, encoding="utf-8")
    return load_intent(path)


@pytest.mark.parametrize("value", ["true", "True", "yes"])
def test_true_with_a_reference_is_accepted(tmp_path, value):
    intent = _intent(tmp_path, f"droits:\n  accord_producteur: {value}\n" + REFERENCE)
    intent.check_rights()
    assert intent.accord_producteur is True and intent.reference_accord.startswith("Accord écrit")


@pytest.mark.parametrize("value", ["non", "oui", "'true'", '"false"', "1", "accord"])
def test_any_other_word_is_refused_with_what_to_write(tmp_path, value):
    with pytest.raises(IntentError) as error:
        _intent(tmp_path, f"droits:\n  accord_producteur: {value}\n" + REFERENCE)
    message = str(error.value)
    assert "écrivez true" in message and "sans guillemets" in message


@pytest.mark.parametrize("rights", ["droits:\n  accord_producteur: false\n" + REFERENCE,
                                    "droits:\n  accord_producteur: no\n" + REFERENCE,
                                    "droits:\n  accord_producteur:\n" + REFERENCE,
                                    "droits:\n" + REFERENCE,
                                    ""])
def test_no_permission_is_refused(tmp_path, rights):
    with pytest.raises(RightsError, match="accord du producteur"):
        _intent(tmp_path, rights).check_rights()


@pytest.mark.parametrize("reference", ["", "  reference: ''\n", "  reference:\n"])
def test_a_permission_without_its_reference_is_refused(tmp_path, reference):
    intent = _intent(tmp_path, "droits:\n  accord_producteur: true\n" + reference)
    with pytest.raises(RightsError, match="pas de référence"):
        intent.check_rights()


def test_rights_written_on_one_line_are_explained(tmp_path):
    with pytest.raises(IntentError, match="deux lignes"):
        _intent(tmp_path, "droits: oui\n")
