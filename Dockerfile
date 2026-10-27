# The app as an image: pinned base, hash-checked dependencies, non-root user, read-only friendly.
#   docker compose --profile app up -d --wait app      (starts Keycloak first)
FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

# The packaging tools are not needed to run the service, and their vendored libraries are what vulnerability
# scanners most often flag in a slim image: remove them.
RUN pip uninstall -y pip setuptools

RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 CMD ["oidc-login-health"]
CMD ["gunicorn", "-c", "python:oidc_login.interfaces.gunicorn_conf", "oidc_login.interfaces.wsgi:build_app()"]
