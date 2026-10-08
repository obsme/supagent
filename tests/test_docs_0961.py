"""Documents and sites (0.9.6.1): a site's certificate checked, checked with a CA file, or not checked (the
document's choice, else docs.verify_tls / docs.ca_bundle), a certificate not trusted said with the two ways to read
the site; a repository's code read (files "code") without the files that hold keys and with the secrets written in
the code masked; a repository read again only as far as it changed (the same commit: nothing read; another: only
the files changed between the two), its unchanged files keeping their pieces in the search."""

from __future__ import annotations

import datetime as dt
import ipaddress
import ssl

import pytest

from test_docs_readers import SECRET, Mock, _doc, env, servers  # noqa: F401  (the fixtures)


# --------------------------------------------------------------------------------------------- #
# the site's certificate
# --------------------------------------------------------------------------------------------- #
@pytest.fixture()
def tls_server(tmp_path):
    """A local HTTPS server whose certificate (self-signed, for 127.0.0.1) no system CA trusts; its certificate file
    is the CA file that trusts it."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test site")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    crt, pem = tmp_path / "site.crt", tmp_path / "site.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    m = Mock(lambda path, q, h: (200, {"Content-Type": "text/html"},
                                 "<html><head><title>Runbook</title></head><body><p>Restart the web first.</p></body></html>"))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(crt), str(pem))
    m.server.socket = context.wrap_socket(m.server.socket, server_side=True)
    yield m.base.replace("http://", "https://") + "/kb/", str(crt)
    m.close()


def test_a_certificate_not_trusted_says_how_to_read_the_site(env, tls_server):
    from supagent.knowledge import docs as D

    url, ca = tls_server
    d = _doc(url, max_pages=1)
    out = D.refresh(d)
    assert out["status"] == "error" and "the site's certificate is not trusted by this server" in d.error
    assert "give its CA file" in d.error and "switch off the certificate check of this document" in d.error
    d.auth = {"verify_tls": False}                                   # the document's choice: not checked
    assert D.refresh(d)["status"] == "ok" and "Restart the web first." in d.content
    d.auth, d.content = {"ca_bundle": ca}, None                      # checked, with the company's CA file
    assert D.refresh(d)["status"] == "ok" and "Restart the web first." in d.content
    d.auth = None
    env["docs.ca_bundle"] = ca                                       # the same for every document
    assert D.refresh(d)["status"] == "ok"
    env["docs.ca_bundle"], env["docs.verify_tls"] = "", False        # not checked for every document
    assert D.refresh(d)["status"] == "ok"
    d.auth = {"verify_tls": True}                                    # a document that wants it checked
    assert D.refresh(d)["status"] == "error"
    d.auth = {"ca_bundle": "/nowhere/ca.pem"}
    env["docs.verify_tls"] = True
    assert D.refresh(d)["status"] == "error" and "the CA file /nowhere/ca.pem is not on this server" in d.error


def test_the_page_sets_the_certificate_check_and_the_files_of_a_repository(ctx, tmp_path):
    from supagent.knowledge import docs as D
    from supagent.models import Doc

    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    d = Doc(kind="url", url="https://git.example.com/projects/OPS/repos/app/browse")
    D.configure(d, {"verify_tls": False, "files": "code"})
    assert d.auth == {"verify_tls": False, "files": "code"} and D.sign_in(d) is None
    D.configure(d, {"auth": {"type": "bearer"}, "secret": SECRET, "ca_bundle": str(ca), "verify_tls": None})
    assert d.auth == {"type": "bearer", "ca_bundle": str(ca), "files": "code"} and D.sign_in(d) is not None
    said = D.describe_auth(d)
    assert said["type"] == "bearer" and said["verify_tls"] is None and said["ca_bundle"] == str(ca)
    assert said["files"] == "code" and SECRET not in str(said)
    D.configure(d, {"auth": {"type": "none"}, "files": "docs"})      # the sign-in removed, the CA file kept
    assert d.auth == {"ca_bundle": str(ca)} and d.secret is None
    with pytest.raises(D.DocError, match="not on this server"):
        D.configure(d, {"ca_bundle": "/nowhere/ca.pem"})
    with pytest.raises(D.DocError, match="files: docs"):
        D.configure(d, {"files": "binaries"})


# --------------------------------------------------------------------------------------------- #
# a repository's code
# --------------------------------------------------------------------------------------------- #
def test_which_files_of_a_repository_are_read(ctx):
    from supagent.knowledge.docs import wanted_file

    assert wanted_file("README.md") and wanted_file("docs/run.md") and wanted_file("db/jobs.sql")
    assert not wanted_file("src/app.py") and wanted_file("src/app.py", "code")
    for path in ("src/Main.java", "web/app.ts", "deploy/Dockerfile", "Makefile", "infra/main.tf", "cmd/run.go",
                 "scripts/backup.sh", "build.gradle", "pom.xml", "Jenkinsfile"):
        assert wanted_file(path, "code"), path
    for path in (".env", "config/.env.prod", "certs/server.key", "keys/id_rsa", "deploy/secrets.yaml", "app.pem",
                 "node_modules/lib/index.js", "dist/app.min.js", "web/bundle.js.map", "package-lock.json",
                 "vendor/lib/a.go", "build/out.py", "img/logo.png", "tool.exe", "poetry.lock"):
        assert not wanted_file(path, "code"), path


def test_the_secrets_written_in_the_code_are_masked(ctx):
    from supagent.knowledge.docs import mask_secrets

    code = """DB_PASSWORD = "Pa55-word!"
api_key: abcdef1234567890
"client_secret": "x9y8z7w6"
url = "postgresql://svc:hunter2pass@db.example.com/app"
headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"}
password = os.environ["DB_PASSWORD"]
token = get_token()
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA
-----END RSA PRIVATE KEY-----
aws = AKIAABCDEFGHIJKLMNOP
retries = 3"""
    out, n = mask_secrets(code)
    for secret in ("Pa55-word!", "abcdef1234567890", "x9y8z7w6", "hunter2pass", "eyJhbGciOiJIUzI1NiJ9", "MIIEowIBAAKCAQEA",
                   "AKIAABCDEFGHIJKLMNOP"):
        assert secret not in out, secret
    assert 'DB_PASSWORD = "***"' not in out and "DB_PASSWORD = ***" in out
    assert 'password = os.environ["DB_PASSWORD"]' in out and "token = get_token()" in out   # no value: kept
    assert "postgresql://svc:***@db.example.com/app" in out and "[a private key, masked]" in out
    assert "retries = 3" in out and n == 7


class Repo:
    """A Bitbucket Data Center repository at a commit: its files, the commits, what changed between two."""

    def __init__(self, files: dict[str, str], commit: str) -> None:
        self.files, self.commit, self.history = dict(files), commit, {commit: dict(files)}

    def move_to(self, commit: str, files: dict[str, str]) -> None:
        self.commit, self.files = commit, dict(files)
        self.history[commit] = dict(files)

    def route(self, path, q, h):
        api = "/bb/rest/api/1.0/projects/OPS/repos/app"
        if h.get("authorization") != f"Bearer {SECRET}":
            return 401, {}, {"errors": [{"message": "Authentication required"}]}
        if path == api + "/commits":
            return 200, {}, {"values": [{"id": self.commit}], "isLastPage": True}
        if path == api + "/files":
            names = sorted(self.files)
            return 200, {}, {"values": names, "isLastPage": True, "start": 0, "size": len(names)}
        if path == api + "/changes":
            old, new = self.history[q["since"]], self.history[q["until"]]
            values = [{"path": {"toString": p}, "type": "DELETE" if p not in new else "ADD" if p not in old else "MODIFY"}
                      for p in sorted(set(old) | set(new)) if old.get(p) != new.get(p)]
            return 200, {}, {"values": values, "isLastPage": True}
        if path.startswith(api + "/raw/"):
            name, at = path[len(api + "/raw/"):], q.get("at")
            files = self.history.get(at, self.files)
            return (200, {"Content-Type": "text/plain"}, files[name]) if name in files else (404, {}, "no")
        return 404, {}, "no"


def test_a_repository_is_read_again_only_as_far_as_it_changed(env, servers):
    from supagent.knowledge import docs as D
    from supagent.knowledge.index import pieces

    repo = Repo({"README.md": "# App\nThe billing app.", "src/app.py": "PASSWORD = 'tiger-2030'\ndef run():\n    pass\n",
                 "src/jobs.py": "def nightly():\n    return 'invoices'\n", "web/app.min.js": "x", ".env": "TOKEN=abc"},
                "c1")
    s = servers(repo.route)
    d = _doc(f"{s.base}/bb/projects/OPS/repos/app/browse", max_pages=50, auth={"type": "bearer", "files": "code"},
             secret=SECRET)
    out = D.refresh(d)
    assert out["status"] == "ok", out
    assert [p["path"] for p in d.pages] == ["README.md", "src/app.py", "src/jobs.py"]   # no .env, no min.js
    assert "tiger-2030" not in d.content and "PASSWORD = ***" in d.content          # the secret masked
    assert all(p["commit"] == "c1" for p in d.pages)
    before = {p["ref"]: p for p in pieces(("doc:",)) if p["ref"].startswith(f"doc:{d.id}#")}
    asked = len(s.got)
    out = D.refresh(d)                                               # the same commit: nothing read
    assert out["status"] == "ok" and not out["changed"]
    assert [r["path"].rsplit("/", 1)[-1] for r in s.got[asked:]] == ["commits"]
    repo.move_to("c2", {"README.md": "# App\nThe billing app.", "src/app.py": "PASSWORD = 'tiger-2030'\ndef run():\n    return 1\n",
                        "src/new.py": "def report():\n    return 'weekly'\n", ".env": "TOKEN=abc"})
    asked = len(s.got)
    out = D.refresh(d)                                               # another commit: only what changed
    assert out["status"] == "ok" and out["changed"]
    raw = sorted(r["path"].split("/raw/", 1)[1] for r in s.got[asked:] if "/raw/" in r["path"])
    assert raw == ["src/app.py", "src/jobs.py", "src/new.py"]       # changed, deleted (404), added
    assert not any(r["path"].endswith("/files") for r in s.got[asked:])
    assert [p["path"] for p in d.pages] == ["README.md", "src/app.py", "src/new.py"]
    assert "return 1" in d.content and "weekly" in d.content and "invoices" not in d.content
    assert all(p["commit"] == "c2" for p in d.pages)
    after = {p["ref"]: p for p in pieces(("doc:",)) if p["ref"].startswith(f"doc:{d.id}#")}
    readme = [r for r, p in before.items() if "The billing app." in p["text"]]
    assert readme and all(after.get(r) == before[r] for r in readme)  # an unchanged file keeps its pieces


def test_a_repository_whose_server_says_no_commit_is_read_in_full(env, servers):
    from supagent.knowledge import docs as D

    repo = Repo({"README.md": "# App\nRead me.", "src/a.py": "A = 1\n"}, "c1")

    def route(path, q, h):
        if path.endswith("/commits") or path.endswith("/changes"):
            return 404, {}, "no"                                     # an older server, a token without that right
        return repo.route(path, q, h)

    s = servers(route)
    d = _doc(f"{s.base}/bb/projects/OPS/repos/app/browse", max_pages=50, auth={"type": "bearer", "files": "code"},
             secret=SECRET)
    assert D.refresh(d)["status"] == "ok" and [p["path"] for p in d.pages] == ["README.md", "src/a.py"]
    assert all(p["commit"] == "" for p in d.pages)
    asked = len(s.got)
    assert D.refresh(d)["status"] == "ok"
    assert any(r["path"].endswith("/files") for r in s.got[asked:])  # read in full again, as before 0.9.6.1


@pytest.mark.parametrize("url,api,web,name", [
    ("https://git.example.com/scm/OPS/runbooks.git", "https://git.example.com/rest/api/1.0/projects/OPS/repos/runbooks",
     "https://git.example.com/projects/OPS/repos/runbooks", "OPS/runbooks"),
    ("https://alice@git.example.com/bitbucket/scm/~alice/notes.git",
     "https://git.example.com/bitbucket/rest/api/1.0/projects/~alice/repos/notes",
     "https://git.example.com/bitbucket/users/alice/repos/notes", "~alice/notes"),
    ("https://git.example.com/scm/OPS/runbooks", "https://git.example.com/rest/api/1.0/projects/OPS/repos/runbooks",
     "https://git.example.com/projects/OPS/repos/runbooks", "OPS/runbooks"),
    ("https://bob@bitbucket.org/acme/runbooks.git", "https://api.bitbucket.org/2.0/repositories/acme/runbooks/src",
     "https://bitbucket.org/acme/runbooks", "acme/runbooks"),
    ("https://bitbucket.org/acme/runbooks.git", "https://api.bitbucket.org/2.0/repositories/acme/runbooks/src",
     "https://bitbucket.org/acme/runbooks", "acme/runbooks"),
])
def test_a_repositorys_clone_address_is_read_as_the_repository(app, url, api, web, name):
    from supagent.knowledge.docs import bitbucket_target, detect_reader, origin

    t = bitbucket_target(url)
    assert detect_reader(url) == "bitbucket" and t is not None
    assert (t["api"], t["web"], t["name"], t["path"]) == (api, web, name, "")
    assert origin(url) == origin(web)                                 # the sign-in goes to that site


def test_a_dsn_without_a_scheme_and_a_named_key_are_masked(ctx):
    """(0.9.6.3) Go's MySQL DSN (user:password@tcp(host:port)/db) and a key held by a name that says so (SIGNING_KEY,
    apiKey) given a literal; an e-mail address, an ssh address and a call are not secrets."""
    from supagent.knowledge.docs import mask_secrets

    cases = {'sql.Open("mysql", "app:S3cretPw9@tcp(db-1:3306)/orders")': 'sql.Open("mysql", "app:***@tcp(db-1:3306)/orders")',
             'dsn = "u:pw12345@db-1:5432/x"': 'dsn = "u:***@db-1:5432/x"',
             'const SIGNING_KEY = "abcdefgh12345678";': "const SIGNING_KEY = ***;",
             'apiKey: "zzzzzzzzzzzz"': "apiKey: ***"}
    for text, masked in cases.items():
        assert mask_secrets(text)[0] == masked, text
    for kept in ("email me at someone@example.com", "mailto:ops@example.com", "ssh git@host:repo.git",
                 "cache_key = make_key(x)", 'primary_key = "id"'):
        assert mask_secrets(kept)[0] == kept


def test_a_connection_strings_password_and_a_secret_default_are_masked(ctx):
    """(0.10) A connection string's password with any character up to the next ; (ADO.NET, Npgsql, ODBC), a secret
    given as the default of an environment lookup; an address given as a default stays."""
    from supagent.knowledge.docs import mask_secrets

    for text, masked in [
        ('"Main": "Server=s1;Database=x;User Id=u;Password=Q!w2e3r4;Encrypt=True"',
         '"Main": "Server=s1;Database=x;User Id=u;Password=***;Encrypt=True"'),
        ("ConnectTimeout=30;Pwd=a#b%c;Database=x", "ConnectTimeout=30;Pwd=***;Database=x"),
        ('TOKEN = os.environ.get("API_TOKEN", "tok_live_ABCDEF123")', 'TOKEN = os.environ.get("API_TOKEN", "***")'),
        ("pw = ENV.fetch('DB_PASSWORD', 'hunter2hunter')", "pw = ENV.fetch('DB_PASSWORD', \"***\")"),
    ]:
        assert mask_secrets(text)[0] == masked, text
    for kept in ['url = os.environ.get("RATES_URL", "https://api.example")', "Password=***;"]:
        assert mask_secrets(kept)[0] == kept
