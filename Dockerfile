# tradesights MCP — the screener as tools for the house agent.
#
# network_mode: host in the compose file, matching the chezmoi and jinsen MCP
# servers: LeClanker runs on the ecosystem bridge and reaches host-published
# ports through host.docker.internal.
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Clanker-Labs/tradesights"
LABEL org.opencontainers.image.description="Market disagreement screener — MCP server"

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . "fastmcp>=3,<4"

ENV TRADESIGHTS_MCP_PORT=8094 \
    PYTHONUNBUFFERED=1
EXPOSE 8094
CMD ["python", "-m", "tradesights.mcp_server"]
