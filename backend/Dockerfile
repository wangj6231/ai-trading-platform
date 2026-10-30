FROM rust:1.99.0-bookworm AS rust-toolchain

FROM python:3.12-slim-bookworm AS native-build
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup PATH=/usr/local/cargo/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY rust/utc_alignment /native
RUN pip install --no-cache-dir maturin==1.15.0 \
    && maturin build --locked --release --compatibility linux --manifest-path /native/Cargo.toml --out /wheels

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/docker-entrypoint.sh ./
COPY backend/app ./app
COPY config ./config
COPY --from=native-build /wheels /wheels

RUN pip install --no-cache-dir /wheels/*.whl && pip install --no-cache-dir .
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

CMD ["/app/docker-entrypoint.sh"]
