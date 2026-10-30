# Deploy runbook (nothing here has been run)

Status: prepared only. Do not run any of this until Kamal says OK. Every command below is copy-paste; none prints the GitHub token, and none writes it to `.git/config`.

Before anything: `cd ~/Desktop/nvdia-personal && .venv/bin/python -m pytest -q` (expect everything green except `tests/test_live.py::test_ultra_through_gateway_sees_only_tokens`, a 402 from Token Factory).

## 0. Pre-publish checklist

- Secrets scan, run 2026-10-30: no NEBIUS/Tavily/GitHub token value appears in the working tree or in any commit of the history (exact-value match, plus patterns for `ghp_`, `github_pat_`, `tvly-`, `sk-`, JWTs and private keys). `.env`, `.veil/`, `*.key` and `infra/logs/*` are git-ignored (`infra/logs/deny_log_sample.txt` is the one reviewed exception: a real OpenShell deny log, no identifiers, used by the dry-run test).
- PHI: every patient, plan, provider, ID and address in the repo is synthetic (`demo/profile.json`, `demo/corpus/`, `veil/synth.py`); each PDF is stamped SYNTHETIC. The static bundle (`web/run.json`, `web/run.js`) contains the synthetic values by design and zero local paths (`tests/test_impact.py::test_static_bundle_has_no_local_paths`).
- Known residue: the git history (9 occurrences) still contains `/Users/kamal` from an old `infra/logs/install1.log` that has since been untracked, and every commit is authored `kamalbuilds <geniusamansingh@gmail.com>`. If you do not want that email or path public, use the snapshot route in 1b instead of pushing history.
- LICENSE is MIT ("Veil contributors"). Change the holder name if you want it to read Kamal's name.
- `docs/judge-*.png`, `docs/live-*.png` and `docs/sandbox-deny-live-1440.png` are screenshots of the previous page design. Refresh or drop them before publishing; the new ones are `docs/redesign/flow-after-{1440,390}.png`.

## 1. Public GitHub repo under kamalbuilds

The token lives in `~/.config/github/account.json` at key `kamalbuilds.token`. It is read into the environment of a single command and goes nowhere else.

### 1a. Check the name is free (prints only an HTTP code; 404 = free)

```sh
GH_TOKEN="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.config/github/account.json')))['kamalbuilds']['token'])")" \
  sh -c 'curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/repos/kamalbuilds/veil'
```

### 1b. Create the repo (public) and push

Option 1, push the existing history:

```sh
cd ~/Desktop/nvdia-personal
GH_TOKEN="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.config/github/account.json')))['kamalbuilds']['token'])")" sh -c '
  curl -s -o /dev/null -w "create: %{http_code}\n" -X POST https://api.github.com/user/repos \
    -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
    -d "{\"name\":\"veil\",\"description\":\"Veil: a private paperwork agent. The model reads your bill but never learns who you are, and the ledger proves it. Synthetic data only.\",\"private\":false,\"has_issues\":true}" &&
  GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= \
  GIT_CONFIG_KEY_1=http.extraheader GIT_CONFIG_VALUE_1="Authorization: Basic $(printf "x-access-token:%s" "$GH_TOKEN" | base64)" \
  git push https://github.com/kamalbuilds/veil.git master:main'
```

(`GIT_CONFIG_*` lives only in that process, so nothing lands in `.git/config`; the remote URL is passed inline and no `origin` is added.)

Option 2, push a one-commit snapshot with a noreply author (hides the old email and the `/Users/kamal` residue in history):

```sh
rm -rf /tmp/veil-public && git clone -q --no-local ~/Desktop/nvdia-personal /tmp/veil-public && cd /tmp/veil-public
git checkout -q --orphan main && git add -A
git -c user.name=kamalbuilds -c user.email=kamalbuilds@users.noreply.github.com commit -qm "Veil: private paperwork agent (Nebius x NVIDIA Personal AI hackathon, synthetic data only)"
# then run the same create + push command as Option 1, but with: git push https://github.com/kamalbuilds/veil.git main:main
```

### 1c. Verify (no token needed)

```sh
curl -s https://api.github.com/repos/kamalbuilds/veil | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['full_name'],d['private'],d['default_branch'])"
git ls-remote https://github.com/kamalbuilds/veil.git
```

## 2. Static deploy of `web/` (no backend)

`web/` is self-contained: `index.html`, `veil.css`, `pseudo.js`, `run.js`, `run.json`, `vercel.json`. It runs from the cached `run.js`; judge mode never calls an API; only `localhost` probes `/api/state`. Fonts load from Google Fonts and fall back to system serif/sans if blocked. Refresh the bundle first if you changed anything: `.venv/bin/python -m veil static /tmp/veil-bundle`.

### 2a. Vercel (recommended)

```sh
cd ~/Desktop/nvdia-personal/web
vercel --version            # CLI is installed; if not logged in: vercel login
vercel deploy --prod --yes  # first run asks for project name: veil-judge. No build step, output is the folder itself.
```

Then open the printed URL and the check in 2c. (Alternatively: Vercel dashboard > Add New > Project > import `kamalbuilds/veil` > Root Directory `web` > Framework Preset Other.)

### 2b. GitHub Pages (needs the public repo from step 1)

```sh
cd ~/Desktop/nvdia-personal
GH_TOKEN="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.config/github/account.json')))['kamalbuilds']['token'])")" sh -c '
  rm -rf /tmp/veil-pages && git clone -q --no-local . /tmp/veil-pages && cd /tmp/veil-pages &&
  git checkout -q --orphan gh-pages && git rm -rfq . && git checkout master -- web && git mv -k web/* . 2>/dev/null; rm -rf web; touch .nojekyll &&
  git add -A && git -c user.name=kamalbuilds -c user.email=kamalbuilds@users.noreply.github.com commit -qm "Static judge page" &&
  GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= \
  GIT_CONFIG_KEY_1=http.extraheader GIT_CONFIG_VALUE_1="Authorization: Basic $(printf "x-access-token:%s" "$GH_TOKEN" | base64)" \
  git push https://github.com/kamalbuilds/veil.git gh-pages:gh-pages &&
  curl -s -o /dev/null -w "pages: %{http_code}\n" -X POST https://api.github.com/repos/kamalbuilds/veil/pages \
    -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" -d "{\"source\":{\"branch\":\"gh-pages\",\"path\":\"/\"}}"'
```

URL once built (about a minute): `https://kamalbuilds.github.io/veil/`.

### 2c. Verify the deployed page

```sh
URL=https://kamalbuilds.github.io/veil   # or the Vercel URL
for f in "" veil.css pseudo.js run.js run.json; do curl -s -o /dev/null -w "$f %{http_code}\n" "$URL/$f"; done
curl -s "$URL/run.json" | grep -c "/Users/"      # must print 0
```

Then open it at 1440 and 390 wide and check: the red "Blocked" alert, the $2,463.00 figure, the ledger side panel, and in "Try to break it" that the spaced member id shows HTTP 422.

## 3. After Token Factory credit returns

```sh
scripts/sandbox_hermes_run.sh injection   # then: scripts/sandbox_hermes_run.sh audit
git diff --stat web/ && git add web && git commit -m "Record live model-driven Hermes run" && .venv/bin/python -m veil static /tmp/veil-bundle
```

Then redeploy with 2a or 2b. Rehearse without credit at any time: `DRY_RUN=1 scripts/sandbox_hermes_run.sh injection`.
