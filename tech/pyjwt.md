# PyJWT 2.15 and cryptography

## What it is

**PyJWT** is a Python library for creating and checking JSON Web Tokens (`tech/jwt-and-jwks.md`). It reads the three parts, rebuilds the signing input, and asks a cryptography backend to verify the signature. The backend is **cryptography**, a Python package with prebuilt compiled code that implements RSA, hashes and other primitives. The dependency line `PyJWT[crypto]` asks for the library plus the optional **extra** called `crypto`, which installs `cryptography` (needed for RS256). Pinned: `pyjwt==2.15.1`, `cryptography==50.0.2`, which in turn needs `cffi` and `pycparser`.

## Why this repository uses it

Signature verification is the one place where "write it yourself" is a mistake. The repository uses PyJWT for the cryptography and wraps it so that the policy (which algorithms, which keys, which claim checks) is written down in the repository's own code and tested.

## Where it appears

| Path | What it does with PyJWT or cryptography |
| --- | --- |
| `src/oidc_login/infrastructure/jwks_verifier.py` | `jwt.get_unverified_header`, `jwt.decode`, `PyJWK.from_dict`, the exceptions. |
| `src/oidc_login/interfaces/demo_cli.py` | `jwt.encode` and `rsa.generate_private_key` to forge tokens on purpose for the validator demo. |
| `tests/fakes.py`, `tests/unit/test_jwks_verifier.py` | A `Signer` with its own RSA key to mint good and bad tokens. |
| `pyproject.toml` | `PyJWT[crypto]>=2.9,<3` |

## How it works underneath

1. `jwt.get_unverified_header(token)` splits the token, base64url-decodes the header and returns it as a dictionary. **Nothing is verified**; it only lets you look.
2. `PyJWK.from_dict(entry)` turns one JSON key from a JWKS (`kty`, `n`, `e`, `kid` ...) into a key object with a `.key` attribute that `cryptography` can use.
3. `jwt.decode(token, key, algorithms=[...], options={...})` checks the algorithm against your list, verifies the signature, and, depending on `options`, checks the standard claims (`exp`, `nbf`, `iat`, `aud`, `iss`, `sub`). It returns the payload as a dictionary or raises an exception from `jwt.exceptions`.
4. Exceptions form a family: `InvalidSignatureError` is a kind of `InvalidTokenError`, as are the errors for malformed tokens.

### Ideas you need first

- **A library and an extra.** A library is code others wrote that you install. An **extra** is an optional add-on set a library offers: `PyJWT[crypto]` means "PyJWT plus the packages needed for RSA". Without the extra, RSA signatures cannot be checked.
- **Compiled code.** Some Python packages include code written in C or Rust for speed. `cryptography` is one: it ships prebuilt binaries for each platform, which is why it is pinned and hash-checked.

## Walkthrough of this repository's use

```python
_NO_CLAIM_CHECKS: Options = {
    "verify_signature": True,
    "verify_exp": False,
    "verify_nbf": False,
    "verify_iat": False,
    "verify_aud": False,
    "verify_iss": False,
    "verify_sub": False,
    "verify_jti": False,
}
```
`Options` is PyJWT's typed dictionary of switches (`from jwt.types import Options`). The signature check stays on. Everything else is off *in the library* because the same checks are performed in `domain/claims.py`: exact comparisons with named errors, a configurable leeway, the nonce and `azp`, and no dependency on a library inside the domain layer (the import-linter contract forbids `jwt` there, `tech/import-linter.md`).

```python
try:
    header = jwt.get_unverified_header(id_token)
except InvalidTokenError as error:
    raise SignatureInvalidError("token is malformed") from error
```
Garbage input (`""`, `"not-a-jwt"`, `"a.b.c"`) is an `InvalidTokenError`. The adapter turns every library exception into the repository's own `SignatureInvalidError`, so callers deal with one named error. `raise ... from error` keeps the original in the traceback chain.

```python
try:
    claims = jwt.decode(id_token, key.key, algorithms=[algorithm], options=_NO_CLAIM_CHECKS)
except InvalidSignatureError as error:
    raise SignatureInvalidError() from error
except InvalidTokenError as error:
    raise SignatureInvalidError("token is malformed") from error
return dict(claims)
```
The more specific exception is caught first. `dict(claims)` returns a plain dictionary.

```python
keys[entry["kid"]] = PyJWK.from_dict(entry)
...
except Exception:  # one malformed key must not hide the others
    _log.warning("ignoring an unusable key in the key set", extra={"kid": entry.get("kid")})
```
Keys are built one by one; a bad one is skipped with a warning.

### `cryptography` in the demo and tests

```python
forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
forged = jwt.encode(claims, forger, algorithm="RS256", headers={"kid": header["kid"]})
```
To prove the verifier rejects a token signed by someone else, the demo generates a fresh RSA key (`65537` is the standard public exponent; 2048 bits is the minimum size in use) and signs the real token's claims with it, using the real `kid`. The verifier finds the real public key under that `kid`, the signature does not match, and the answer is `signature verification failed`.

Note `"alg": "none"` can be *encoded* with `jwt.encode(claims, key="", algorithm="none", ...)`; PyJWT can build it, and the verifier is what refuses it.

### Line by line: `src/oidc_login/infrastructure/jwks_verifier.py`

```python
"""ID token signature verification against the provider's published keys (JWKS), with an algorithm allow-list."""
```

The docstring: ID token signature verification against the provider's published keys (a **JWKS**, JSON Web Key Set, a JSON list of public keys), with an algorithm allow-list. `tech/jwt-and-jwks.md` explains the formats.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
```

Imports: `logging`, `threading`, `time`, `Callable` and `Mapping`, `Any`.

```python
import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidSignatureError, InvalidTokenError
from jwt.types import Options
```

`jwt` is PyJWT. `PyJWK` is its class for one public key from a JWKS. `InvalidSignatureError` and `InvalidTokenError` are its error classes; `Options` is the type of its options dictionary.

```python
from oidc_login.domain.errors import SignatureInvalidError, UnsupportedAlgorithmError
```

The two signature errors of the domain.

```python
_log = logging.getLogger("oidc_login.verifier")
# Only asymmetric algorithms, listed by name: "none" and the HMAC family are refused, which closes the
# algorithm-confusion attack in which the public key is used as an HMAC secret.
DEFAULT_ALGORITHMS = ("RS256",)
```

`_log` and `DEFAULT_ALGORITHMS = ("RS256",)`. The comment says only asymmetric algorithms are listed by name, so `none` and the HMAC family are refused. That closes the **algorithm-confusion attack**, in which an attacker signs a token with HMAC using the provider's public key (which is public) as the secret and a naive verifier accepts it.

```python
_NO_CLAIM_CHECKS: Options = {
    "verify_signature": True,
    "verify_exp": False,
    "verify_nbf": False,
    "verify_iat": False,
    "verify_aud": False,
    "verify_iss": False,
    "verify_sub": False,
    "verify_jti": False,
}
```

`_NO_CLAIM_CHECKS` is an options dictionary for PyJWT that turns the signature check on and every claim check off (`exp`, `nbf`, `iat`, `aud`, `iss`, `sub`, `jti`). The domain does the claim checks with named errors and with the nonce, which PyJWT does not know about.

```python
class JwksTokenVerifier:
    """Verifies the signature and algorithm of a JWT; claim checks belong to the domain.

    The key is chosen by the token's ``kid``. An unknown ``kid`` triggers one refetch of the key set (the provider
    may have rotated), at most once per ``min_refresh_seconds``, so a stream of forged tokens cannot make the app
    hammer the provider.
    """
```

`JwksTokenVerifier` verifies the signature and the algorithm. The key is chosen by the token's `kid` (key id). An unknown `kid` triggers one re-fetch of the key set (the provider may have rotated its key) at most once per `min_refresh_seconds`, so a stream of forged tokens cannot make the app hammer the provider.

```python
    def __init__(
        self,
        fetch_jwks: Callable[[], Mapping[str, Any]],
        *,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        min_refresh_seconds: float = 30,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
```

The constructor takes a function that fetches the key set, the allowed algorithms, the minimum seconds between fetches and a clock function (tests pass a fake).

```python
        self._fetch = fetch_jwks
        self._algorithms = algorithms
        self._min_refresh = min_refresh_seconds
        self._monotonic = monotonic
        self._keys: dict[str, PyJWK] = {}
        self._last_fetch: float | None = None
        self._lock = threading.Lock()
```

It stores them, an empty dictionary of keys by `kid`, the time of the last fetch (`None` at first) and a lock.

```python
    def verify(self, id_token: str) -> dict[str, Any]:
        """Return the claims of a token whose signature verifies against the provider's key for its ``kid``."""
        try:
            header = jwt.get_unverified_header(id_token)
        except InvalidTokenError as error:
            raise SignatureInvalidError("token is malformed") from error
```

`verify` first reads the token's header without verifying anything (`get_unverified_header`); a malformed token raises `SignatureInvalidError`.

```python
        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or algorithm not in self._algorithms:
            raise UnsupportedAlgorithmError(str(algorithm))
```

The header's `alg` must be text on the allow-list, else `UnsupportedAlgorithmError`. The algorithm comes from the allow-list check, not from trust in the token.

```python
        key = self._key_for(header.get("kid"), algorithm)
```

The key for the token's `kid` is looked up.

```python
        try:
            claims = jwt.decode(id_token, key.key, algorithms=[algorithm], options=_NO_CLAIM_CHECKS)
        except InvalidSignatureError as error:
            raise SignatureInvalidError() from error
        except InvalidTokenError as error:
            raise SignatureInvalidError("token is malformed") from error
        return dict(claims)
```

`jwt.decode` verifies the signature with that key and only the allowed algorithm `[algorithm]`. A bad signature raises `SignatureInvalidError`; any other token problem raises the same error with "token is malformed". The claims are returned as a plain dictionary.

```python
    def _key_for(self, kid: object, algorithm: str) -> PyJWK:
        if not isinstance(kid, str) or not kid:
            raise SignatureInvalidError("token names no signing key (kid)")
```

`_key_for` requires a `kid` that is non-empty text.

```python
        with self._lock:
            key = self._keys.get(kid)
            if key is None and self._may_refetch():
                self._load(algorithm)
                key = self._keys.get(kid)
```

Under the lock: a known key is returned directly; an unknown one triggers a reload if allowed, then a second lookup.

```python
        if key is None:
            raise SignatureInvalidError("signature verification failed: signing key not found")
        return key
```

Still unknown: the error "signing key not found".

```python
    def _may_refetch(self) -> bool:
        return self._last_fetch is None or self._monotonic() - self._last_fetch >= self._min_refresh
```

`_may_refetch` is true when there was no fetch yet or the minimum time has passed since the last one.

```python
    def _load(self, algorithm: str) -> None:
        self._last_fetch = self._monotonic()
        document = self._fetch()
```

`_load` records the fetch time first (so a failing fetch is also rate-limited) and fetches the document.

```python
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            if not isinstance(entry, dict) or entry.get("use", "sig") != "sig" or not isinstance(entry.get("kid"), str):
                continue
            if entry.get("alg", algorithm) != algorithm:
                continue
```

It builds a new dictionary. Entries that are not objects, whose `use` is not `sig` (signature, not encryption) or that lack a text `kid` are skipped; so are keys whose declared `alg` differs from the token's algorithm.

```python
            try:
                keys[entry["kid"]] = PyJWK.from_dict(entry)
            except Exception:  # one malformed key must not hide the others
                _log.warning("ignoring an unusable key in the key set", extra={"kid": entry.get("kid")})
```

`PyJWK.from_dict` builds the key. One malformed key is logged and skipped so it does not hide the others.

```python
        self._keys = keys
```

The new dictionary replaces the old one, so keys the provider removed are dropped.

## Try it yourself

1. Versions:
   ```bash
   .venv/bin/python -c "import jwt, cryptography; print(jwt.__version__, cryptography.__version__)"
   ```
   Expect `2.15.1 50.0.2`.
2. Sign and verify:
   ```bash
   .venv/bin/python - <<'EOF'
   import jwt
   from cryptography.hazmat.primitives.asymmetric import rsa
   k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
   t = jwt.encode({"sub": "u1"}, k, algorithm="RS256")
   print(jwt.decode(t, k.public_key(), algorithms=["RS256"]))
   other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
   try: jwt.decode(t, other.public_key(), algorithms=["RS256"])
   except jwt.InvalidSignatureError as e: print("rejected:", e)
   EOF
   ```
   Expect `{'sub': 'u1'}` and `rejected: Signature verification failed`.
3. Look without trusting:
   ```bash
   .venv/bin/python -c "
   import jwt
   print(jwt.get_unverified_header('eyJhbGciOiJub25lIiwia2lkIjoieCJ9.e30.'))"
   ```
   Expect `{'alg': 'none', 'kid': 'x'}`: PyJWT reports it; deciding to refuse it is the verifier's job.
4. Run the verifier tests: `.venv/bin/pytest tests/unit/test_jwks_verifier.py -q`. Expect all pass.

## Mistakes people make

- `jwt.decode(token, options={"verify_signature": False})` on input that matters.
- Omitting `algorithms=` or passing the header's value.
- Letting library exceptions escape to the user or the log with token contents.
- Not pinning: the cryptography package ships compiled code, so supply-chain review matters; the lock file pins it with hashes (`tech/uv-and-lock-files.md`).
- Using small RSA keys or weak algorithms when generating test keys; the tests use 2048-bit.

## Check yourself

1. What does `get_unverified_header` verify?
   *Nothing; it only decodes the header.*
2. Why does the verifier pass a one-item `algorithms` list?
   *So the library cannot use any other algorithm, whatever the header says.*
3. What does `PyJWT[crypto]` add?
   *The `cryptography` package, needed for RSA algorithms.*
4. Why are the library's claim checks turned off?
   *The repository does them itself in the domain layer, with named errors and exact rules.*
5. How does the demo forge a token?
   *It signs the real claims with a freshly generated RSA key and the real `kid`.*

## Further reading

- PyJWT documentation (2.x): https://pyjwt.readthedocs.io/en/stable/
- `jwt.decode` options and exceptions: https://pyjwt.readthedocs.io/en/stable/api.html
- cryptography documentation: https://cryptography.io/en/latest/
