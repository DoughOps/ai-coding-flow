FROM python:3.13-slim

WORKDIR /app

# System packages + Node.js (required for opencode engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    unzip  \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install AI coding engines (opencode + claude-code-router + claude CLI)
# claude-code-router is pinned to v2 — v3 contains breaking changes.
RUN npm install -g opencode-ai @musistudio/claude-code-router@2.0.0 @anthropic-ai/claude-code

# Python dependencies (includes aider-chat which installs the aider binary)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# RUN aider-install

# The old version of package cache causes security vulnerabilities and is not needed for our use case, so we disable it.
ENV UV_NO_CACHE=1

# CVE-2026-42284 (gitpython<3.1.47) and CVE-2026-35030 (litellm<1.83.0)
# aider-chat hard-pins litellm==1.81.10 so --with can't override it;
# instead we force-upgrade both packages directly into the tool's venv after install.
RUN uv tool install --force --python 3.12 aider-chat@latest && \
    uv pip install \
        --python "$(uv tool dir)/aider-chat/bin/python" \
        "gitpython>=3.1.47" \
        "litellm>=1.83.0" && \
    python_bin="$(uv tool dir)/aider-chat/bin/python" && \
    exc_file="$(${python_bin} -c 'import aider.exceptions,inspect;print(inspect.getfile(aider.exceptions))')" && \
    sed -i 's/raise ValueError.*exceptions list.*/continue  # skip unknown litellm exceptions/' "${exc_file}"

ENV PATH="/root/.local/bin:${PATH}"

# =================================
# OpenCode installation
# =================================
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/root/.opencode/bin:${PATH}"

# =================================
# Bun installation
# =================================
RUN npm install -g bun
ENV PATH="/root/.bun/bin:${PATH}"

# =================================
# OpenCode Initialize
# =================================
RUN opencode run "test"

# # =================================
# # oh-my-opencode installation
# # =================================
RUN VERSION=$(npm view oh-my-openagent version) \
    && echo "Installing oh-my-openagent version: ${VERSION}" \
    && npx -y oh-my-openagent@${VERSION} install --no-tui --claude=no --gemini=no --copilot=no --openai=no --opencode-zen=no --zai-coding-plan=no \
    && sed -i "s/oh-my-openagent@latest/oh-my-openagent@${VERSION}/" ~/.config/opencode/opencode.jsonc \
    && rm -rf ~/.npm/_npx

COPY . .

RUN git config --global --add safe.directory /tmp/ai-coding-flow || true

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
