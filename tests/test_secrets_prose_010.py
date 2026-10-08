"""(0.10) A secret written in a sentence, in any of the languages teams write in, is masked; a plain word, a reference
or a placeholder after a secret's label is kept."""

from __future__ import annotations

import pytest

PROSE = [
    ("Mot de passe de l'administrateur du tableau de bord : Xy7-Kq2-2031.", True),
    ("Passwort für das Dashboard: Pq4-Lm8-2031.", True),
    ("The admin password is S3cure!pass and must be rotated.", True),
    ("La contraseña es Hola2031!", True),
    ("Kennwort ist geheim123", True),
    ("The API key is AbCdEfGhIjKlMnOp.", True),
    ("password = 'p@ss'", True),
    ("The password is stored in Vault.", False),
    ("Le mot de passe est dans le coffre.", False),
    ("token expiry: 3600 seconds", False),
    ("secret: none", False),
    ("Use the token from the vault: vault:secret/data/app", False),
    ("password: <your password>", False),
    ("The password policy: 12 characters minimum.", False),
    ("Rotate the token every 90 days.", False),
    ("the password file is /etc/app/pw.txt", False),
    ("If the token is expired, renew it.", False),
    ("The secret is that nobody reads the docs.", False),
    ("token = get_token()", False),
]


@pytest.mark.parametrize("text,masked", PROSE)
def test_a_secret_written_in_a_sentence_in_any_language(ctx, text, masked):
    from supagent.knowledge.docs import mask_secrets

    out, n = mask_secrets(text)
    assert (out != text) is masked, (text, out)
    if masked:
        assert "***" in out and n >= 1
