"""T14 · Subtitle files in UTF-8, UTF-16, Windows-1256 (Arabic subtitles made on Windows) and
Windows-1252 are read exactly; nothing is ever replaced by « � » behind the reader's back; the
encoding found is reported; a file Wasf cannot read stops with a clear message."""
import pytest

from wasf.cli import main
from wasf.gaps import SubtitleError, decode_subtitles, load_subtitles, parse_subtitles
from wasf.pipeline import prepare
from wasf.project import load_project

# Tunisian Arabic (Derja) as it appears in subtitles, with shadda, Tunisian spellings and one
# French word glued to an Arabic article, as people write it.
DERJA = ["شنوّة صار؟ علاش ما جيتش البارح؟",
         "ما فمّاش مشكل، توّا نجي.",
         "يزّي عاد، برّا روّح للدّار.",
         "نحبّ نحكي معاك على حاجة مهمّة.",
         "الـwifi ما يخدمش، عيشك شوف معايا."]
FRENCH = ["— Tu viens ? — Ça dépend.", "École fermée à cause de la grève.",
          "Œuvre d'art, Île de Djerba. À demain !"]
TIMES = [(1.0, 3.0), (6.0, 8.5), (12.0, 14.0), (19.0, 21.0), (25.0, 27.0)]


def _srt(lines, newline="\n"):
    def tc(t):
        return f"00:00:{int(t):02d},{round((t % 1) * 1000):03d}"
    blocks = [f"{i}{newline}{tc(a)} --> {tc(b)}{newline}{text}"
              for i, ((a, b), text) in enumerate(zip(TIMES, lines), 1)]
    return (newline * 2).join(blocks) + newline


@pytest.mark.parametrize("encoding,expected,newline", [
    ("utf-8", "utf-8", "\n"),
    ("utf-8-sig", "utf-8", "\r\n"),      # with a byte-order mark, Windows line ends
    ("cp1256", "cp1256", "\r\n"),        # Arabic subtitles saved by Windows tools
    ("utf-16", "utf-16", "\r\n"),        # « Unicode » in Windows Notepad
    ("utf-16-le", "utf-16", "\r\n"),     # UTF-16 saved without its byte-order mark
    ("utf-16-be", "utf-16", "\n"),
    ("iso8859_6", "iso8859_6", "\n"),     # the older Arabic code page
])
def test_tunisian_arabic_subtitles_are_read_exactly(tmp_path, encoding, expected, newline):
    path = tmp_path / "derja.srt"
    path.write_bytes(_srt(DERJA, newline).encode(encoding))
    cues, found, warnings = load_subtitles(path)
    assert found == expected and warnings == []
    assert [c.text for c in cues] == DERJA
    assert [(c.start, c.end) for c in cues] == TIMES
    assert not any("�" in c.text for c in cues)


def test_a_letter_windows_1256_cannot_hold_still_works_in_utf8(tmp_path):
    line = "ڨال لي نجي غدوة."            # ڨ, the Tunisian /g/, has no place in Windows-1256
    with pytest.raises(UnicodeEncodeError):
        line.encode("cp1256")
    path = tmp_path / "g.srt"
    path.write_text(_srt([line]), encoding="utf-8")
    assert parse_subtitles(path)[0].text == line


def test_french_windows_1252_is_not_mistaken_for_arabic(tmp_path):
    path = tmp_path / "fr.srt"
    path.write_bytes(_srt(FRENCH, "\r\n").encode("cp1252"))
    cues, found, _ = load_subtitles(path)
    assert found == "cp1252" and [c.text for c in cues] == FRENCH
    # The trap it avoids: the same bytes read as Windows-1256 put Arabic letters into French words.
    assert "ةcole" in path.read_bytes().decode("cp1256")


def test_arabic_windows_1256_is_not_mistaken_for_latin(tmp_path):
    data = _srt(DERJA[:4]).encode("cp1256")
    assert "ÕÇÑ" in data.decode("cp1252")          # what a Latin reading would have shown
    assert decode_subtitles(data)[1] == "cp1256"


def test_the_two_arabic_code_pages_are_not_mistaken_for_each_other(tmp_path):
    iso = _srt(DERJA).encode("iso8859_6")
    assert "جêتش" in iso.decode("cp1256")         # wrong letters, but nothing replaced by « � »
    assert decode_subtitles(iso)[1] == "iso8859_6"
    windows = _srt(DERJA).encode("cp1256")
    assert decode_subtitles(windows) == (_srt(DERJA), "cp1256")


def test_unreadable_file_stops_with_a_clear_message(tmp_path):
    path = tmp_path / "abime.srt"
    path.write_bytes(b"1\r\n00:00:01,000 --> 00:00:02,000\r\n\x81\xc7bc d\xc9f g\x8dh\r\n")
    with pytest.raises(SubtitleError) as error:
        load_subtitles(path)
    assert "UTF-8" in str(error.value) and "abime.srt" in str(error.value)


def test_replacement_characters_already_in_the_file_are_reported(tmp_path):
    path = tmp_path / "deja.srt"
    path.write_text(_srt(["Une réplique ab�mée."]), encoding="utf-8")
    _cues, found, warnings = load_subtitles(path)
    assert found == "utf-8" and len(warnings) == 1 and "illisibles" in warnings[0]


def test_utf16_without_byte_order_mark_is_not_read_as_utf8(tmp_path):
    # Plain-ASCII lines in UTF-16 are also valid UTF-8, with a zero byte after each letter:
    # read that way, the file gave no cue at all, and no warning.
    lines = ["Tu viens ?", "On se voit demain.", "Merci, bonne nuit."]
    data = _srt(lines, "\r\n").encode("utf-16-le")
    assert "\x00" in data.decode("utf-8")
    path = tmp_path / "ascii16.srt"
    path.write_bytes(data)
    cues, found, warnings = load_subtitles(path)
    assert found == "utf-16" and warnings == [] and [c.text for c in cues] == lines
    path.write_bytes(_srt(FRENCH, "\r\n").encode("utf-16-be"))
    assert [c.text for c in load_subtitles(path)[0]] == FRENCH


@pytest.mark.parametrize("data", [
    b"Bonjour.\nCeci est une liste de dialogues, sans aucun minutage.\n",
    "WEBVTT\n\nNOTE minutage perdu\n\nشنوّة صار؟\n".encode(),
])
def test_a_file_with_text_but_no_cue_stops(tmp_path, data):
    path = tmp_path / "sans_minutage.srt"
    path.write_bytes(data)
    with pytest.raises(SubtitleError) as error:
        load_subtitles(path)
    assert "Aucune réplique" in str(error.value) and "--sous-titres" in str(error.value)


def test_stray_zero_bytes_stop_instead_of_being_read(tmp_path):
    path = tmp_path / "zeros.srt"
    path.write_bytes(_srt(FRENCH).encode("utf-8") + b"\x00\x00")
    with pytest.raises(SubtitleError, match="Impossible de lire"):
        load_subtitles(path)


@pytest.mark.parametrize("data", [b"", b"\xef\xbb\xbf\r\n", b"WEBVTT\n\n"])
def test_an_empty_subtitle_file_only_warns(tmp_path, data):
    path = tmp_path / "vide.srt"
    path.write_bytes(data)
    cues, _found, warnings = load_subtitles(path)
    assert cues == [] and len(warnings) == 1 and "silences" in warnings[0]


def test_prepare_reports_and_keeps_the_encoding(demo_files, tmp_path):
    srt = tmp_path / "derja_1256.srt"
    srt.write_bytes(_srt(DERJA, "\r\n").encode("cp1256"))
    logs = []
    path = prepare(demo_files["video"], demo_files["intention"], sous_titres=srt, langue="aeb",
                   fournisseur="mock", sortie=tmp_path / "projet", log=logs.append)
    assert any("encodage Windows-1256 (arabe)" in line for line in logs)
    project = load_project(path)
    assert project.encodage_sous_titres == "cp1256"
    context = " ".join(s.dialogue_avant + " " + s.dialogue_apres for s in project.segments)
    assert "ما فمّاش مشكل" in context and "�" not in context


def test_prepare_and_the_command_line_refuse_an_unreadable_file(demo_files, tmp_path, capsys):
    srt = tmp_path / "abime.srt"
    srt.write_bytes(b"1\r\n00:00:01,000 --> 00:00:02,000\r\n\x81\xc7bc d\xc9f\r\n")
    with pytest.raises(SubtitleError):
        prepare(demo_files["video"], demo_files["intention"], sous_titres=srt,
                fournisseur="mock", sortie=tmp_path / "projet", log=lambda _m: None)
    assert not (tmp_path / "projet" / "projet.json").exists()
    code = main(["preparer", str(demo_files["video"]), "--intention", str(demo_files["intention"]),
                 "--sous-titres", str(srt), "--fournisseur", "mock",
                 "--sortie", str(tmp_path / "projet2")])
    assert code == 1 and "Impossible de lire" in capsys.readouterr().err
