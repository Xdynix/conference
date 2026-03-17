FROM debian:trixie-slim

ARG APP_USER=main
ARG APP_UID=900
ARG APP_PORT=8000

RUN groupadd --system --gid ${APP_UID} ${APP_USER} && \
    useradd --system --uid ${APP_UID} --gid ${APP_USER} --home-dir /home/${APP_USER} ${APP_USER}

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates

ENV HOME=/home/${APP_USER}
WORKDIR ${HOME}
RUN chown ${APP_USER}:${APP_USER} ${HOME}
ENV PATH="${HOME}/.venv/bin:$PATH"
ENV PYTHONPATH="${HOME}"

COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1 \
    UV_NO_SYNC=1

# Runs as root intentionally: the BuildKit cache mount defaults to root:root,
# and the resulting .venv is read-only at runtime (UV_COMPILE_BYTECODE
# pre-compiles .pyc files). Do not move USER before this step.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project --no-default-groups --group prod

COPY --chown=${APP_USER}:${APP_USER} . .

# Propagate to supervisord via %(ENV_*)s expansion.
ENV APP_USER=${APP_USER} APP_PORT=${APP_PORT}

EXPOSE ${APP_PORT}
# The healthcheck URL has no FORCE_SCRIPT_NAME prefix because granian receives
# requests after the sidecar nginx strips the subpath.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${APP_PORT}/api/health-status')"
USER ${APP_USER}

ENV STATIC_ROOT=${HOME}/staticfiles
RUN python manage.py collectstatic --noinput && \
    mkdir -p var

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["supervisord", "-c", "docker/supervisord.conf"]
