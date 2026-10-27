# JWT, JWS and JWKS

## What it is

A **JWT** (JSON Web Token, RFC 7519) is a compact, signed piece of data. It is three pieces of **base64url** text joined by dots: `header.payload.signature`. **Base64url** is a way to write bytes using only letters, digits, `-` and `_` so the result is safe inside a URL. The header and the payload are JSON objects. The payload holds **claims**: statements such as "the user is `u1`". The signature is made with a private key by the party that issues the token, and anyone with the matching public key can check it. A signed JWT is formally a **JWS** (JSON Web Signature, RFC 7515).

A **JWKS** (JSON Web Key Set, RFC 7517) is a JSON document listing public keys, each with a `kid` (key id), a key type, a use (`sig` for signatures) and the key's numbers. An identity provider publishes its JWKS at a URL (the `jwks_uri` in its discovery document) so that anyone can verify its tokens.

## Why this repository uses it

An OpenID Connect ID token is a JWT. The app must be sure that the token really came from the provider and was not changed. That is the signature check. The famous failures are all about *trusting what the token says about itself*: `"alg": "none"` (no signature at all), switching to a symmetric algorithm so the public key becomes the "secret", or accepting any `kid`. This repository refuses each, and a unit test builds each attack by hand.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/oidc_login/infrastructure/jwks_verifier.py` | `JwksTokenVerifier`: header read, algorithm allow-list, key lookup by `kid`, signature check. |
| `src/oidc_login/domain/claims.py` | The claim checks that run after the signature is known good. |
| `src/oidc_login/infrastructure/oidc_provider.py` | `jwks()` fetches the key set from `jwks_uri`. |
| `tests/unit/test_jwks_verifier.py` | The attacks: wrong key, tampered payload, `none`, algorithm confusion, malformed tokens, missing `kid`, key rotation. |
| `tests/fakes.py` | A `Signer` that generates RSA keys and mints tokens for the tests. |

## How it works underneath

1. The provider builds `header` (`{"alg":"RS256","kid":"key-1","typ":"JWT"}`) and `payload` (the claims), base64url-encodes each, joins them with a dot (`signing input`), and signs that text with its **private** key using the algorithm in `alg`. RS256 means RSA with SHA-256: the signature can be made only with the private key and checked with the public key.
2. The token is `base64url(header).base64url(payload).base64url(signature)`.
3. The verifier decodes the header, picks the public key whose `kid` matches from the JWKS, and checks the signature over the first two parts. Any change to the header or payload, even one character, makes the check fail.
4. Only after the signature is good does it make sense to read claims.

Signing is **not** encryption: anyone can read the payload (just decode it). The signature only proves who made it and that it is unchanged.

**The common claims** (the ones this app checks): `iss` (issuer: who made it), `sub` (subject: the user's stable id), `aud` (audience: who it is for), `exp` (expiry, seconds since 1970), `iat` (issued at), `nonce` (the value the client sent), `azp` (authorized party), `at_hash` (a fingerprint of the access token delivered together).

**Why the algorithm list matters.** The header is chosen by whoever made the token, which may be an attacker. If a verifier believed `alg`: with `none` there is no signature; with `HS256` (HMAC, a shared-secret scheme) a library that is careless might use the provider's *public* key, which everyone knows, as the shared secret, and the attacker can compute a valid HMAC. The defense is to decide the allowed algorithms in your own code, not from the token.

## Walkthrough of this repository's use

```python
DEFAULT_ALGORITHMS = ("RS256",)
```
Only RS256, named explicitly.

```python
header = jwt.get_unverified_header(id_token)
algorithm = header.get("alg")
if not isinstance(algorithm, str) or algorithm not in self._algorithms:
    raise UnsupportedAlgorithmError(str(algorithm))
key = self._key_for(header.get("kid"), algorithm)
claims = jwt.decode(id_token, key.key, algorithms=[algorithm], options=_NO_CLAIM_CHECKS)
```
Read the header **without trusting it** (`get_unverified_header`), refuse unless the algorithm is on our list, find the key, then decode with `algorithms=[algorithm]`, a one-element list, so the library cannot be talked into another algorithm. `_NO_CLAIM_CHECKS` switches off PyJWT's own `exp`/`aud`/`iss` checks (`verify_signature` stays on) because those checks live in `domain/claims.py` where each failure has its own named error and can be tested without a library.

```python
if not isinstance(kid, str) or not kid:
    raise SignatureInvalidError("token names no signing key (kid)")
with self._lock:
    key = self._keys.get(kid)
    if key is None and self._may_refetch():
        self._load(algorithm)
        key = self._keys.get(kid)
```
Keys are cached by `kid`. An unknown `kid` means either a forged token or that the provider rotated its keys, so the verifier refetches the JWKS, but **at most once every 30 seconds** (`min_refresh_seconds`), so a stream of garbage tokens cannot make the app hammer the provider.

```python
for entry in document.get("keys", []):
    if not isinstance(entry, dict) or entry.get("use", "sig") != "sig" or not isinstance(entry.get("kid"), str):
        continue
    if entry.get("alg", algorithm) != algorithm:
        continue
    keys[entry["kid"]] = PyJWK.from_dict(entry)
```
Use only signature keys that declare the expected algorithm; one malformed key is logged and skipped, not fatal.

Keycloak's realm file sets `"defaultSignatureAlgorithm": "RS256"`, so the provider and the allow-list agree.

### The attacks, as tests

`test_jwks_verifier.py` has: a token signed by a different key but the same `kid` (rejected: `signature verification failed`); one changed byte in the payload (`sub` set to `admin`; rejected); `alg: none` (rejected before any key lookup); the HS256 confusion attack, assembled by hand because PyJWT refuses to build it; a table of malformed tokens; a token with no `kid`; and rotation: a new `kid` triggers one refetch.

## Try it yourself

1. Build and read a JWT:
   ```bash
   .venv/bin/python - <<'EOF'
   import jwt, json, base64
   from cryptography.hazmat.primitives.asymmetric import rsa
   key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
   token = jwt.encode({"iss": "https://idp.example.test", "sub": "u1", "aud": "notes-app", "exp": 2000000000},
                      key, algorithm="RS256", headers={"kid": "key-1"})
   header, payload, signature = token.split(".")
   decode = lambda part: json.loads(base64.urlsafe_b64decode(part + "=="))
   print(decode(header)); print(decode(payload)); print(len(signature))
   EOF
   ```
   Expect `{'alg': 'RS256', 'kid': 'key-1', 'typ': 'JWT'}`, the claims, and `342` (a 2048-bit RSA signature).
2. Watch the algorithm allow-list refuse a different algorithm:
   ```bash
   .venv/bin/python -c "
   import jwt
   from cryptography.hazmat.primitives.asymmetric import rsa
   k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
   t = jwt.encode({'sub': 'u1'}, k, algorithm='RS256')
   jwt.decode(t, k.public_key(), algorithms=['HS256'])"
   ```
   Expect `jwt.exceptions.InvalidAlgorithmError: The specified alg value is not allowed`.
3. Run the attack tests:
   ```bash
   .venv/bin/pytest tests/unit/test_jwks_verifier.py -v
   ```
   Expect all to pass, with names that read like the attacks above.
4. Read a real provider's key set (needs Keycloak up):
   ```bash
   curl -s http://localhost:8180/realms/demo/protocol/openid-connect/certs | python3 -m json.tool | head -20
   ```
   Expect a `keys` list with `kid`, `kty: RSA`, `alg: RS256`, `use: sig`, `n` and `e`.

## Mistakes people make

- Decoding the payload and trusting it without verifying the signature.
- Reading `alg` from the token to choose the algorithm.
- Accepting `none`.
- Using the public key as an HMAC secret.
- Not checking `iss`, `aud`, `exp`, `nonce` after the signature check.
- Fetching the JWKS on every request, or refetching without a limit when a token has an unknown `kid`.
- Believing a JWT is encrypted. It is only signed.
- Clock skew: a tiny difference between the two machines' clocks makes a fresh token look expired or not-yet-valid. The checks allow 30 seconds of leeway.

## Check yourself

1. What are the three parts of a JWT?
   *Header, payload and signature, each base64url-encoded, joined by dots.*
2. Is the payload secret?
   *No; anyone can decode it. The signature proves origin and integrity.*
3. Which key signs, and which verifies, with RS256?
   *The private key signs; the matching public key verifies.*
4. Why does the verifier use its own list of algorithms?
   *The header is controlled by the sender; trusting it enables `none` and HMAC-confusion attacks.*
5. What does `kid` select?
   *Which public key in the JWKS to verify with.*

## Further reading

- RFC 7519, JWT: https://www.rfc-editor.org/rfc/rfc7519
- RFC 7515, JWS: https://www.rfc-editor.org/rfc/rfc7515
- RFC 7517, JWK: https://www.rfc-editor.org/rfc/rfc7517
- RFC 8725, JWT best current practices: https://www.rfc-editor.org/rfc/rfc8725
- jwt.io introduction (decoder): https://jwt.io/introduction
