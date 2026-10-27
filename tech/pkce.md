# PKCE (Proof Key for Code Exchange, RFC 7636)

## What it is

PKCE (said "pixie") is an add-on to the OAuth authorization code flow (`tech/oauth2-and-openid-connect.md`). It makes a stolen authorization code useless. Before the login starts, the client invents a secret, the **code verifier**. It sends the provider only a one-way fingerprint of it, the **code challenge**. At the end, when it trades the code for tokens, the client must present the verifier. The provider hashes it and compares. An attacker who intercepts the code (for example from the redirect URL) does not have the verifier, so the exchange fails.

## Why this repository uses it

PKCE is the cure for authorization-code interception, and current OAuth security guidance (RFC 9700) asks for it for all clients, not only public ones. This repository uses it for the confidential client (`notes-app`) as defense in depth, and the demo shows it for a public client (`notes-spa`), where it is the *only* thing protecting the exchange because there is no client secret.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/oidc_login/domain/pkce.py` | `is_valid_verifier` and `challenge_for`: the pure rule (21 lines). |
| `src/oidc_login/application/login_flow.py` | `start()` makes the verifier and sends only the challenge; `complete()` sends the verifier. |
| `src/oidc_login/infrastructure/oidc_provider.py` | Adds `code_challenge` and `code_challenge_method=S256` to the authorization URL, and `code_verifier` to the token request. |
| `idp/realm-demo.json` | `"pkce.code.challenge.method": "S256"` on both clients: the provider requires it. |
| `tests/unit/test_pkce.py` | Checks the RFC's own example. |
| `src/oidc_login/interfaces/demo_cli.py` | `wrong_pkce_verifier` and `public_client_needs_pkce` steps. |

## How it works underneath

1. Client: pick a random verifier, 43 to 128 characters from `A-Z a-z 0-9 - . _ ~`.
2. Client: compute `challenge = base64url(SHA-256(verifier))`, with no `=` padding. This is the method called `S256`.
3. Client to provider (in the browser redirect): `code_challenge=<challenge>&code_challenge_method=S256`. The provider stores the challenge with the code it will issue.
4. Client to provider (back channel, later): the code plus `code_verifier=<verifier>`.
5. Provider: hash the verifier and compare with the stored challenge. If they differ: `invalid_grant`.

A hash is one-way, so seeing the challenge does not reveal the verifier. The older method `plain` sends the verifier itself and gives no protection against anyone who sees the request; this repository uses only `S256`.

## Walkthrough of this repository's use

```python
_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")

def is_valid_verifier(verifier: str) -> bool:
    return _VERIFIER.fullmatch(verifier) is not None
```
The RFC's allowed alphabet and length, with `fullmatch` so the whole string must conform.

```python
def challenge_for(verifier: str) -> str:
    if not is_valid_verifier(verifier):
        raise ValueError("code verifier must be 43 to 128 unreserved characters")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
```
SHA-256 of the verifier's ASCII bytes gives 32 bytes; `urlsafe_b64encode` turns them into text using `-` and `_` instead of `+` and `/`; `.rstrip(b"=")` removes the padding, as the RFC requires. The result is always 43 characters.

In `start()` the verifier is `self._tokens.token(64)`: 64 random bytes, which `secrets.token_urlsafe` encodes as 86 characters, inside the allowed range. The verifier is stored in `PendingLogin.code_verifier` (declared `field(repr=False)` so it never prints) and never leaves the server except in the back-channel call.

The demo's `wrong_pkce_verifier` step gets a real code from Keycloak and tries to exchange it with a different verifier. It expects the provider to answer `invalid_grant`. `public_client_needs_pkce` does the same for the public `notes-spa` client, which has no secret: a code obtained with a challenge cannot be exchanged without the verifier (Keycloak answers 400), and the same exchange with the verifier succeeds (200).

## Try it yourself

1. Reproduce the RFC's example (appendix B):
   ```bash
   .venv/bin/python -c "
   from oidc_login.domain.pkce import challenge_for
   print(challenge_for('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'))"
   ```
   Expect `E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`.
2. Check the validator:
   ```bash
   .venv/bin/python -c "
   from oidc_login.domain.pkce import is_valid_verifier
   import secrets
   print(is_valid_verifier('short'), is_valid_verifier(secrets.token_urlsafe(64)))"
   ```
   Expect `False True`.
3. Run the tests: `.venv/bin/pytest tests/unit/test_pkce.py -q`. Expect all pass.
4. With Keycloak up (`make up`), run `make demo` and find the two steps about the PKCE verifier. Expect both `PASS`.

## Mistakes people make

- Using `plain` instead of `S256`.
- A short or predictable verifier. Use at least 32 random bytes.
- Reusing one verifier for many logins. Each attempt has its own.
- Sending the verifier in the authorization request (it must stay secret until the exchange).
- Not requiring PKCE at the provider, so a client that skips it is still accepted. The realm file sets the method on both clients.
- Padding characters (`=`) left in the challenge.

## Check yourself

1. What is sent in the browser redirect: the verifier or the challenge?
   *The challenge, a hash of the verifier.*
2. What does an attacker with a stolen code still lack?
   *The verifier.*
3. Which hash does `S256` use?
   *SHA-256, then URL-safe base64 without padding.*
4. How long is a challenge?
   *43 characters.*
5. Why does a public client need PKCE even more?
   *It has no client secret, so PKCE is the only proof the exchange comes from the client that started the login.*

## Further reading

- RFC 7636, PKCE: https://www.rfc-editor.org/rfc/rfc7636
- RFC 9700, OAuth 2.0 Security Best Current Practice (PKCE for all clients): https://www.rfc-editor.org/rfc/rfc9700
- Python `hashlib` and `base64`: https://docs.python.org/3.12/library/hashlib.html and https://docs.python.org/3.12/library/base64.html
