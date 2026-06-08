FROM python:3.11-slim

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
RUN npm install -g opencode-ai @musistudio/claude-code-router @anthropic-ai/claude-code

# Python dependencies (includes aider-chat which installs the aider binary)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =================================
# OpenCode installation
# =================================
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/home/vscode/.opencode/bin:${PATH}"

# =================================
# Bun installation
# =================================
RUN curl -fsSL https://bun.com/install | bash
ENV PATH="/home/vscode/.bun/bin:${PATH}"

# =================================
# OpenCode Initialize
# =================================
RUN opencode run "test"

# # =================================
# # oh-my-opencode installation
# # =================================
# RUN VERSION=$(npm view oh-my-openagent version) \
#     && echo "Installing oh-my-openagent version: ${VERSION}" \
#     && npx -y oh-my-openagent@${VERSION} install --no-tui --claude=no --gemini=no --copilot=no --openai=no --opencode-zen=no --zai-coding-plan=no \
#     && sed -i "s/oh-my-openagent@latest/oh-my-openagent@${VERSION}/" ~/.config/opencode/opencode.jsonc \
#     && rm -rf ~/.npm/_npx

COPY . .

RUN git config --global --add safe.directory /tmp/ai-coding-flow || true

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
