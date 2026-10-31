FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/Hafsa-Anwar65/deadcode-finder" \
      org.opencontainers.image.description="Find and safely remove dead Python code" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /app

# Mount your project at /code:  docker run --rm -v "$PWD:/code" ghcr.io/hafsa-anwar65/deadcode-finder
WORKDIR /code
ENTRYPOINT ["deadcode-finder"]
CMD ["."]
