FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install '.[web,live]'
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/runs /data/evals /data/gold \
    && chown -R app /data
USER app
CMD ["research-web", "--help"]
