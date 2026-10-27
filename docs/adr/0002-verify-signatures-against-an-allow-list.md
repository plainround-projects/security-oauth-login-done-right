# 2. Verify ID token signatures against an allow-list of algorithms

Date: 2026-10-27. Status: accepted.

## Context

A JWT names its own algorithm. A verifier that trusts the header can be told `none`, or told `HS256` and given the provider's public key as the HMAC secret (algorithm confusion). Either way the signature check passes on a token the attacker made. The lesson's sample passes a fixed `algorithms=["RS256"]` list to the library; this project keeps that and makes the failures observable.

## Decision

`JwksTokenVerifier` reads the unverified header and refuses any algorithm not on its list (RS256) with `UnsupportedAlgorithmError`, naming the algorithm. It requires a `kid`, looks the key up in the cached JWKS, refetches the set once for an unknown `kid` (at most once every 30 seconds, so forged tokens cannot make the app hammer the provider) and verifies with exactly that key and algorithm. Keys marked `use: enc`, keys of another algorithm and malformed keys are skipped. Claim checks are off in the library call and run in the domain, after the signature, so each failure has its own named error and reason.

## Alternatives

- **Let the library check claims too.** Fewer lines, but one generic error family; the lesson asks for a distinct reason per failure.
- **Trust `jku` or `x5u` headers to find keys.** Attacker-controlled URLs; never.

## Consequences

- Adding an algorithm (ES256, PS256) is a one-line change to the allow-list plus a test; the default stays narrow.
- A key rotation at the provider is picked up on the next token with the new `kid`; tokens signed with a key the provider retired fail after the set refreshes.
