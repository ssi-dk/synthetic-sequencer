FROM python:3.12.16-slim-bookworm
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# Hash-pinned bootstrap from the Python eMudhra security advisory.
RUN python -m pip --isolated --disable-pip-version-check install --no-cache-dir --no-deps --upgrade \
    'pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70' \
    && python -m pip install --no-cache-dir .
USER 20001:20000
ENTRYPOINT ["synthetic-sequencer"]
