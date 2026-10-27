# CycloneDX SBOM (`cyclonedx-bom` 7.5)

## What it is

An **SBOM** (software bill of materials) is a machine-readable list of the ingredients of a piece of software: every package, its exact version, where it came from, and a hash of the file. **CycloneDX** is an open standard format for an SBOM (JSON or XML), maintained by OWASP. **cyclonedx-bom** is the Python package that provides the command `cyclonedx-py`, which writes a CycloneDX file from a requirements file or an environment. Pinned: `cyclonedx-bom==7.5.0` (with `cyclonedx-python-lib==11.12.0`).

## Why this repository uses it

When a new vulnerability is announced ("library X, versions below 2.3"), the first question is "do we use it?". An SBOM answers that in seconds, for every release, without logging in to a machine. The lesson asks for dependency audit plus SBOM in CI; this repository writes one for the locked **runtime** dependencies and uploads it as a build artifact.

## Where it appears

| Path | What it does |
| --- | --- |
| `Makefile` target `sbom` | `cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json` |
| `.github/workflows/ci.yml` | Runs `make sbom` and uploads `sbom.cdx.json` as the artifact `sbom-cyclonedx`. |
| `sbom.cdx.json` | The generated file. It is listed in `.gitignore` and `.dockerignore`: it is built, not stored. |
| `pyproject.toml` | `cyclonedx-bom>=5,<8` in the `dev` extras. |

## How it works underneath

1. `cyclonedx-py requirements <file>` reads each pinned `name==version` line, including its `--hash=` options.
2. For each package it writes a **component**: name, version, a package URL (`purl`) such as `pkg:pypi/flask@3.1.3`, and the file hashes from the lock.
3. It adds a `metadata` block (tool, time, a unique `serialNumber`) and a `dependencies` list.
4. The output is one JSON document with `bomFormat: CycloneDX` and a `specVersion`.

## Walkthrough of this repository's use

```make
sbom: $(STAMP) ## write sbom.cdx.json (CycloneDX) for the locked runtime dependencies
	$(VENV)/bin/cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json
	@echo "wrote sbom.cdx.json"
```
- `requirements` is the sub-command that reads a requirements file (others read an environment, Poetry or Pipenv files).
- `requirements.lock` (not the dev lock) means the SBOM describes what ships in the container: 20 components.
- `--of JSON` sets the output format; `-o` the file.

The result on this repository: `bomFormat` `CycloneDX`, `specVersion` `1.6`, and these components: `anyio`, `blinker`, `certifi`, `cffi`, `click`, `cryptography`, `flask`, `gunicorn`, `h11`, `httpcore`, `httpx`, `idna`, `itsdangerous`, `jinja2`, `markupsafe`, `packaging`, `pycparser`, `pyjwt`, `typing-extensions`, `werkzeug`. Note that the SBOM lists the *runtime* packages that `pip install` pulled in, not Python itself or the operating-system packages of the base image. A container-image SBOM (tools such as Syft) would cover those; the pipeline lesson in this series builds that.

In CI:
```yaml
- run: make sbom
- uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
  with:
    name: sbom-cyclonedx
    path: sbom.cdx.json
```
After every run the SBOM can be downloaded from the workflow run page.

## Try it yourself

1. Write it:
   ```bash
   make sbom
   ```
   Expect `wrote sbom.cdx.json`.
2. Count and list components:
   ```bash
   python3 -c "import json; d = json.load(open('sbom.cdx.json')); print(d['bomFormat'], d['specVersion'], len(d['components'])); print(sorted(c['name'] for c in d['components']))"
   ```
   Expect `CycloneDX 1.6 20` and the list above.
3. Look at one component's hashes:
   ```bash
   python3 -c "import json; d = json.load(open('sbom.cdx.json')); print(json.dumps(d['components'][0], indent=1)[:700])"
   ```
   Expect a component with `name`, `version` and `externalReferences` holding `SHA-256` hashes.
4. Ask the "do we use it?" question:
   ```bash
   grep -c '"name": "werkzeug"' sbom.cdx.json
   ```
   Expect `1` (or more if the name also appears in a reference).

## Mistakes people make

- Generating the SBOM from loose `>=` ranges or from a developer's laptop. Here it comes from the same lock file the container installs.
- Committing the generated file and letting it drift. It is regenerated in CI and not tracked.
- Believing an SBOM is a vulnerability scan. It is only the list; `pip-audit` (`tech/pip-audit.md`) is the check.
- Forgetting that it does not list the OS packages in the image.

## Check yourself

1. What does an SBOM contain?
   *The components of the software: names, versions, package URLs and hashes.*
2. Why generate it from `requirements.lock` and not `requirements-dev.lock`?
   *It should describe what ships, and development tools are not shipped.*
3. Why is `sbom.cdx.json` not tracked in git?
   *It is a build output; CI regenerates it for each run.*
4. Which spec version does the file declare?
   *CycloneDX 1.6.*
5. Which tool actually finds vulnerabilities?
   *`pip-audit`, not the SBOM.*

## Further reading

- CycloneDX specification: https://cyclonedx.org/specification/overview/
- cyclonedx-python (`cyclonedx-bom`) documentation: https://cyclonedx-bom-tool.readthedocs.io/en/stable/
- Package URL (purl) specification: https://github.com/package-url/purl-spec
