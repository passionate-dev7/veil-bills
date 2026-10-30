#!/usr/bin/env bash
# M0: non-interactive NemoHermes onboarding -> Nebius Token Factory (custom OpenAI-compatible provider).
# Key is read from the user's zsh env (NEBIUS_API_KEY) and never printed.
set -euo pipefail
. "$HOME/.nvm/nvm.sh" >/dev/null; nvm use 24 >/dev/null
# brew-less PATH: OpenShell's Homebrew install fails on this Mac (outdated CLT), so the standalone binaries in ~/.local/bin are used.
export PATH="/tmp/nobrew-bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export COMPATIBLE_API_KEY="$(zsh -ic 'printf %s "$NEBIUS_API_KEY"' 2>/dev/null)"
export NEMOCLAW_PROVIDER=custom
export NEMOCLAW_ENDPOINT_URL=https://api.tokenfactory.nebius.com/v1
export NEMOCLAW_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b
export NEMOCLAW_REASONING="${NEMOCLAW_REASONING:-false}"
export NEMOCLAW_SANDBOX_NAME=veil-hermes
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"  # Colima socket (no /var/run/docker.sock on this Mac)
export NEMOCLAW_POLICY_TIER=restricted
export NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8090}"  # 8080 is held by an existing ssh tunnel on this Mac
exec nemohermes onboard --non-interactive --yes --yes-i-accept-third-party-software "$@"
