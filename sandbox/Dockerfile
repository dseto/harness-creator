# Imagem do sandbox efêmero do harness.
# Construir: docker build -t harness-sandbox:latest sandbox/
#
# Princípios:
#   - tudo que o agente precisa já vem na imagem (o contêiner roda SEM rede);
#   - usuário não-root;
#   - nenhuma credencial ou estado do host.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Toolchain de teste pré-instalado (sandbox não tem rede para instalar depois).
RUN pip install --no-cache-dir pytest pytest-asyncio ruff mypy

RUN useradd --create-home --shell /bin/sh agent
USER agent
WORKDIR /workspace

CMD ["sleep", "infinity"]
