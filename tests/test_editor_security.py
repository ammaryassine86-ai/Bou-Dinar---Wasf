"""S01/S02 · Only the editor's own page, on this computer, can read or change the project.

Covered: the session token on every API call and every change, foreign origins (CSRF), foreign
Host headers (DNS rebinding), cross-site fetches, non-JSON bodies, framing, and an editor that
only ever listens on a loopback address. The last tests run a real server on a socket."""
import http.client
import json
import re
import socket
import subprocess
import sys
import threading
import time

import pytest
from editeur_client import editor_client
from werkzeug.serving import make_server

from wasf.cli import main
from wasf.editor.app import (
    TOKEN_HEADER,
    EditorHostError,
    check_host,
    create_app,
    host_name,
    is_loopback,
)
from wasf.pipeline import prepare
from wasf.project import load_project


@pytest.fixture(scope="module")
def project(demo_files, tmp_path_factory):
    return prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], fournisseur="mock",
                   sortie=tmp_path_factory.mktemp("securite") / "projet", log=lambda _m: None)


def _bare(path):
    """A client that does not know the token: another page, or a script."""
    return create_app(path).test_client()


def test_api_calls_need_the_session_token(project):
    bare = _bare(project)
    assert bare.get("/api/projet").status_code == 403
    before = load_project(project).segments[0].texte
    for path, body in (("/api/passage/p001", {"action": "enregistrer", "texte": "Piégé."}),
                       ("/api/projet", {"realisateur": "Quelqu'un d'autre"}),
                       ("/api/valider-sans-alerte", {})):
        assert bare.post(path, json=body).status_code == 403
        wrong = bare.post(path, json=body, headers={TOKEN_HEADER: "devine"})
        assert wrong.status_code == 403
    after = load_project(project)
    assert after.segments[0].texte == before and after.realisateur != "Quelqu'un d'autre"
    good = editor_client(project)
    assert good.get("/api/projet").status_code == 200
    assert good.post("/api/projet", json={"realisateur": "Réalisatrice A"}).status_code == 200


def test_a_new_editor_session_has_a_new_token(project):
    first, second = create_app(project), create_app(project)
    assert first.config["WASF_JETON"] != second.config["WASF_JETON"]
    assert len(first.config["WASF_JETON"]) >= 40


def test_cross_site_requests_are_refused_even_with_the_token(project):
    client = editor_client(project)
    for headers in ({"Origin": "https://evil.example"},
                    {"Origin": "http://127.0.0.1:9999"},          # another local web app
                    {"Origin": "null"},                            # sandboxed frame, file://
                    {"Sec-Fetch-Site": "cross-site"},
                    {"Sec-Fetch-Site": "same-site"}):
        answer = client.post("/api/valider-sans-alerte", json={}, headers=headers)
        assert answer.status_code == 403, headers
    # A plain HTML form (the classic CSRF) can neither add the header nor send JSON.
    form = _bare(project).post("/api/valider-sans-alerte", data={"x": "1"},
                               headers={"Origin": "https://evil.example"})
    assert form.status_code == 403
    assert not any(s.valide_en_lot for s in load_project(project).segments)
    # The page itself: same origin, same-origin fetch.
    own = client.post("/api/projet", json={"realisateur": "Réalisatrice A"},
                      headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert own.status_code == 200


def test_a_body_must_be_json(project):
    client = editor_client(project)
    answer = client.post("/api/projet", data='{"realisateur": "X"}', content_type="text/plain")
    assert answer.status_code == 415


@pytest.mark.parametrize("host", ["attacker.example:8765", "attacker.example", "192.168.1.20:8765",
                                  "127.0.0.1.attacker.example", "localhost.attacker.example:8765",
                                  "[2001:db8::1]:8765", ""])
def test_foreign_host_headers_are_refused(project, host):
    """DNS rebinding: the attacker's name points at 127.0.0.1, so the request arrives here,
    but its Host header still carries the attacker's name."""
    client = editor_client(project)
    for path in ("/", "/api/projet", "/images/p001_1.jpg", "/static/editor.js"):
        assert client.get(path, headers={"Host": host}).status_code == 403, (host, path)
    assert client.post("/api/projet", json={"realisateur": "X"},
                       headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765", "127.0.0.1",
                                  "LOCALHOST:8765", "127.0.0.2:8765"])
def test_loopback_host_headers_are_accepted(project, host):
    assert editor_client(project).get("/api/projet", headers={"Host": host}).status_code == 200


def test_the_page_carries_the_token_and_cannot_be_framed(project):
    app = create_app(project)
    page = app.test_client().get("/", headers={"Sec-Fetch-Site": "none"})
    assert page.status_code == 200
    assert f'name="wasf-jeton" content="{app.config["WASF_JETON"]}"' in page.get_data(as_text=True)
    assert page.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert page.headers["Cache-Control"] == "no-store"
    framed = app.test_client().get("/", headers={"Sec-Fetch-Site": "cross-site",
                                                 "Sec-Fetch-Dest": "iframe"})
    assert framed.status_code == 403


def test_host_rules():
    assert host_name("127.0.0.1:8765") == "127.0.0.1" and host_name("[::1]:8765") == "::1"
    assert host_name("localhost") == "localhost"
    for good in ("127.0.0.1", "localhost", "::1", "[::1]", "127.8.9.10", "LocalHost"):
        assert is_loopback(good), good
    for bad in ("0.0.0.0", "::", "192.168.1.10", "10.0.0.2", "attacker.example", "",
                "localhost.attacker.example", "127.0.0.1.nip.io"):
        assert not is_loopback(bad), bad


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "monpc.local"])
def test_the_editor_refuses_to_listen_on_the_network(project, host, capsys):
    with pytest.raises(EditorHostError):
        check_host(host)
    assert main(["relire", str(project), "--hote", host, "--sans-navigateur"]) == 1
    assert "n'écoute que sur cet ordinateur" in capsys.readouterr().err


# --------------------------------------------------------------------------- a real server
@pytest.fixture()
def server(project):
    app = create_app(project)
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, app
    httpd.shutdown()


def _request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_dns_rebinding_against_a_running_editor(server, project):
    httpd, _app = server
    port = httpd.server_port
    # After rebinding, the attacker's page is « same-origin » with its own name: the browser
    # sends Host and Origin with that name, and no Sec-Fetch-Site objection.
    rebinding = {"Host": f"attacker.example:{port}", "Origin": f"http://attacker.example:{port}",
                 "Sec-Fetch-Site": "same-origin"}
    assert _request(port, "GET", "/", rebinding)[0] == 403          # cannot read the token
    assert _request(port, "GET", "/api/projet", rebinding)[0] == 403
    status, _ = _request(port, "POST", "/api/valider-sans-alerte",
                         {**rebinding, "Content-Type": "application/json"}, b"{}")
    assert status == 403


def test_unauthorized_requests_against_a_running_editor(server, project):
    httpd, app = server
    port = httpd.server_port
    local = f"127.0.0.1:{port}"
    # Another page (or local web app) fires a request without the token.
    for headers in ({"Host": local, "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
                    {"Host": local, "Origin": "http://127.0.0.1:3000", "Sec-Fetch-Site": "same-site"},
                    {"Host": local}):
        status, _ = _request(port, "POST", "/api/projet",
                             {**headers, "Content-Type": "application/json"},
                             json.dumps({"validation_realisateur": True}).encode())
        assert status == 403, headers
    assert load_project(project).validation_realisateur is False
    # The editor's own page: it gets the token from the page it was served, then uses it.
    status, page = _request(port, "GET", "/", {"Host": local, "Sec-Fetch-Site": "none"})
    token = re.search(r'name="wasf-jeton" content="([^"]+)"', page.decode()).group(1)
    assert token == app.config["WASF_JETON"]
    status, data = _request(port, "GET", "/api/projet", {"Host": local, TOKEN_HEADER: token,
                                                         "Sec-Fetch-Site": "same-origin"})
    assert status == 200 and json.loads(data)["projet"]["film"]


def _non_loopback_address():
    """An address of this computer on a real network interface, if it has one."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))        # no packet is sent for UDP
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_wasf_relire_listens_on_loopback_only(project):
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "wasf", "relire", str(project), "--port", str(port),
                             "--sans-navigateur"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("l'éditeur n'a pas démarré")
        outside = _non_loopback_address()
        if outside:
            with pytest.raises(OSError):
                socket.create_connection((outside, port), timeout=1).close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
