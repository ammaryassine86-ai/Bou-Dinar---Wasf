"""The review editor as its own page talks to it: a loopback host, no foreign origin, and the
session token on every request (S01/S02). Tests that play the director use this client;
tests that play an attacker use a bare create_app(...).test_client()."""
from wasf.editor.app import TOKEN_HEADER, create_app


def editor_client(project_path):
    app = create_app(project_path)
    client = app.test_client()
    client.environ_base["HTTP_" + TOKEN_HEADER.upper().replace("-", "_")] = app.config["WASF_JETON"]
    return client
