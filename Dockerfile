FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
USER 20001:20000
ENTRYPOINT ["synthetic-sequencer"]
