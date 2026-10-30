# Veil M0: NemoClaw + OpenShell + Hermes on macOS (written 2026-10-29, IST)

Result: WORKS on macOS (Apple Silicon, Colima/Docker). No fallback to plain Docker needed.
Stack: NemoClaw v0.0.137 (`nemohermes`), OpenShell 0.0.116 (docker-driver gateway as a HOST process, 127.0.0.1:8090, mTLS), Hermes 0.21.3 in sandbox `veil-hermes`, Colima (vz, 4 CPU, 6 GB).

## Shell env needed for every nemohermes/openshell call
    . ~/.nvm/nvm.sh; nvm use 24
    export PATH="$HOME/.local/bin:$PATH" DOCKER_HOST="unix://$HOME/.colima/default/docker.sock" NEMOCLAW_GATEWAY_PORT=8090

## 1. Colima
COLIMA_HOME stays on internal disk (the full home on exFAT hung). Only the 30 GB datadisk is a symlink to
/Volumes/PortableSSD/nvdia/personal/colima-datadisk/datadisk (works on exFAT, but is fully allocated, not sparse).
    colima start --cpu 4 --memory 6 --vm-type vz --runtime docker

## 2. Install + onboard (Token Factory baseline): infra/onboard.sh
Workarounds: (a) CLT is too old for Homebrew installs, so brew is hidden from PATH (/tmp/nobrew-bin has symlinks to colima, limactl, jq) and
the standalone OpenShell binaries get installed into ~/.local/bin; (b) port 8080 is held by a user ssh tunnel, so gateway port 8090;
(c) DOCKER_HOST must point at the Colima socket or the gateway fails with "Socket not found: /var/run/docker.sock".
Key is read at runtime with `zsh -ic 'printf %s "$NEBIUS_API_KEY"'` into COMPATIBLE_API_KEY. It is never printed or written.
Core env: NEMOCLAW_PROVIDER=custom NEMOCLAW_ENDPOINT_URL=https://api.tokenfactory.nebius.com/v1 NEMOCLAW_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b
NEMOCLAW_SANDBOX_NAME=veil-hermes NEMOCLAW_POLICY_TIER=restricted, then
    nemohermes onboard --non-interactive --yes --yes-i-accept-third-party-software --fresh
Verified: `openshell sandbox exec -n veil-hermes -- hermes chat -q "..." -Q` answers via Token Factory.

## 3. KEY QUESTION: route sandbox inference to a host-local gateway: YES, WORKS
Path: Hermes -> https://inference.local (in sandbox) -> OpenShell gateway process on host -> http://127.0.0.1:8000/v1 (Veil gateway) -> Token Factory.
Run `infra/onboard-local.sh` (NEMOCLAW_ENDPOINT_URL=http://127.0.0.1:8000/v1, NEMOCLAW_COMPATIBLE_AUTH_MODE=none, no COMPATIBLE_API_KEY, `--recreate-sandbox`).
Constraints found:
- The inference router runs on the HOST, so the endpoint must resolve from the host (127.0.0.1), not host.openshell.internal (that gave HTTP 503).
- NemoClaw only qualifies loopback no-auth endpoints on port 8000 (NEMOCLAW_VLLM_PORT) or 11434. So the Veil gateway should listen on 127.0.0.1:8000.
  `openshell inference set` alone is refused until onboarding has qualified the endpoint.
- The sandbox never holds the Token Factory key. The gateway holds it. Direct Token Factory is blocked (see policy).
- Verified with infra/stub_gateway.py (logs JSON with auth redacted, forwards to Token Factory): requests arrive with header `Via: 1.1 openshell-sandbox`;
  GET /v1/models and POST /v1/chat/completions forwarded with 200. Hermes returned VEIL-LOCAL-OK.
- Known cosmetic issue: onboarding ends with "Native local provider attachment does not match the selected Hermes sandbox" (registry publication).
  Sandbox works, but `nemohermes list` may not show it. Try `nemohermes onboard --resume` if needed.
- Direct containers also reach host servers on 127.0.0.1 via host.openshell.internal (192.168.5.2), which is how the policy below allows the gateway.

## 4. Egress policy (OpenShell YAML): infra/policy/veil-egress-gateway-only.yaml
Schema: version, filesystem_policy, landlock, process, network_policies.<name>.{endpoints[{host,port,protocol,enforcement,allowed_ips,rules[{allow:{method,path}}]}],binaries[{path}]}.
Default is deny. Anything not listed is blocked (L4 `opa` engine, or L7 per-method/path for allowed hosts).
    openshell policy get veil-hermes --full
    openshell policy set veil-hermes --policy infra/policy/veil-egress-gateway-only.yaml --wait
    openshell logs veil-hermes --source sandbox -n 400
Allowlist = host.openshell.internal:8000 (GET /v1/models, POST /v1/chat/completions, /v1/responses; allowed_ips 192.168.0.0/16) + the managed inference.local route.
It drops the restricted-tier extras (nous_research, nvidia, pypi, ollama 11435 provider).
Test results after applying (policy v2), run in the sandbox with curl:
    https://evil.example/exfil -> 000 (blocked)    http://evil.example/ -> 403
    https://api.tokenfactory.nebius.com/v1/models -> 000 (blocked)
    GET  host.openshell.internal:8000/v1/models -> 200 (allowed, hit the stub)
    POST host.openshell.internal:8000/v1/embeddings -> 403 (path not in rules)
    GET  host.openshell.internal:8791/v1/models -> 403 (other port)
    hermes chat -q ... -> VEIL-LOCKED-OK (still works under the tight policy)
Deny log lines (infra/logs/deny_log_sample.txt):
    [1793267452.424] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(1940) -> evil.example:443 [policy:- engine:opa] [reason:endpoint evil.example:443 is not allowed by any policy]
    [1793267452.461] [sandbox] [OCSF ] [ocsf] HTTP:GET [MED] DENIED /usr/bin/curl(1951) -> GET http://evil.example/ [policy:- engine:opa] [reason:endpoint evil.example:80 is not allowed by any policy]
    [1793267452.506] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(1962) -> api.tokenfactory.nebius.com:443 [policy:- engine:opa] [reason:endpoint api.tokenfactory.nebius.com:443 is not allowed by any policy]
    [1793267452.550] [sandbox] [OCSF ] [ocsf] HTTP:GET [INFO] ALLOWED /usr/bin/curl(1973) -> GET http://host.openshell.internal:8000/v1/models [policy:veil_gateway engine:l7]
    [1793267464.298] [sandbox] [OCSF ] [ocsf] HTTP:POST [MED] DENIED /usr/bin/curl(1987) -> POST http://host.openshell.internal:8000/v1/embeddings [policy:veil_gateway engine:l7] [reason:FORWARD_L7 deny POST host.openshell.internal:8000/v1/embeddings reason=POST /v1/embeddings not permitted by policy]
Caveat: a re-onboard (--recreate-sandbox) resets the policy to the tier defaults, so re-apply the YAML afterwards.

## 5. Hermes API
Hermes OpenAI-compatible API runs in the sandbox on :8642 (health OK, version 0.21.3). Key is API_SERVER_KEY in /sandbox/.hermes/.env inside the sandbox
(`nemohermes veil-hermes gateway-token` failed to fetch it). Verified in-sandbox POST /v1/chat/completions -> "VEIL-API-OK".
Host access: `openshell forward start 8642 veil-hermes -d` makes http://127.0.0.1:8642 reachable on the Mac (health 200 verified). Send `Authorization: Bearer <API_SERVER_KEY>`.
Read the key at runtime with: openshell sandbox exec -n veil-hermes -- sh -c 'grep ^API_SERVER_KEY= /sandbox/.hermes/.env' (do not log it).

## 6. Resources (idle, after tests)
Colima VM 4 CPU / 5.77 GiB; sandbox container ~327 MiB RAM, ~0.7% CPU idle. Docker images 3.7 GB. ~/.colima 5.0 GB internal, ~/.nemoclaw 1.0 GB internal.
Colima datadisk on SSD: 30 GB (fully allocated on exFAT). Inside VM root overlay: 18 GB size, 4.8 GB used.
WARNING: internal Data volume was at 2.7 GiB free (100%) at the end, and was ~12 GB at the start. Free internal space is tight.

## 7. Side effects / notes
- Installer ran a Homebrew auto-update (not revertible). I ran `brew untap nvidia/openshell` and `brew developer off`.
- Pre-existing `latch-web` container (port 8080) and the ssh tunnel were left untouched.
- infra/stub_gateway.py is a throwaway stub on 127.0.0.1:8000. Replace it with the real Veil gateway on the same port.
