#!/usr/bin/env bash
# M0 step 4: onboard the sandbox against a HOST-LOCAL gateway (stub or Veil) instead of Token Factory.
# The OpenShell gateway process runs on the Mac host, so it dials 127.0.0.1:<port> itself.
# NemoClaw only qualifies loopback endpoints without auth on port 8000 (or 11434), so the gateway must listen on 127.0.0.1:8000.
# No Nebius key is given to NemoClaw/OpenShell/sandbox here; the host gateway holds the upstream key.
set -euo pipefail
. "$HOME/.nvm/nvm.sh" >/dev/null; nvm use 24 >/dev/null
export PATH="/tmp/nobrew-bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
unset COMPATIBLE_API_KEY
export NEMOCLAW_PROVIDER=custom
export NEMOCLAW_ENDPOINT_URL=http://127.0.0.1:8000/v1
export NEMOCLAW_COMPATIBLE_AUTH_MODE=none
export NEMOCLAW_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b
export NEMOCLAW_REASONING="${NEMOCLAW_REASONING:-false}"
export NEMOCLAW_SANDBOX_NAME=veil-hermes
export NEMOCLAW_POLICY_TIER=restricted
export NEMOCLAW_GATEWAY_PORT=8090
exec nemohermes onboard --non-interactive --yes --yes-i-accept-third-party-software --recreate-sandbox "$@"
