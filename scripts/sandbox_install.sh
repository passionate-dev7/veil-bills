#!/bin/sh
# Install Veil into the OpenShell sandbox `veil-hermes` (idempotent). Corpus is SYNTHETIC. Run from the repo root.
# 1) policy v3 (gateway-only + four exact /tools/veil paths)  2) three skills  3) corpus, read-only  4) the `veil` tool helper
set -e
SB=veil-hermes; STAGE=.veil/stage; rm -rf $STAGE; mkdir -p $STAGE/corpus $STAGE/skills/health
openshell policy set $SB --policy policy/veil-egress-sandbox-tools.yaml --wait
for s in eob-audit appeal-letter deductible-tracker; do cp -R skills/$s $STAGE/skills/health/$s; cat sandbox/skill-tail.md >> $STAGE/skills/health/$s/SKILL.md; done
cp ${VEIL_CORPUS:-.veil/inbox}/*.pdf $STAGE/corpus/
.venv/bin/python - <<PY
from pathlib import Path
from veil.extract import pdf_text
for p in Path("$STAGE/corpus").glob("*.pdf"):
    p.with_suffix(".txt").write_text(pdf_text(p))
PY
openshell sandbox exec -n $SB -- sh -c 'chmod -R u+w /sandbox/corpus 2>/dev/null; rm -rf /sandbox/corpus /sandbox/bin /sandbox/.hermes/skills/health'
openshell sandbox upload $SB $STAGE/skills/health /sandbox/.hermes/skills
openshell sandbox upload $SB $STAGE/corpus /sandbox
openshell sandbox upload $SB sandbox/veil /sandbox/bin
openshell sandbox exec -n $SB -- sh -c 'chmod -R u+w /sandbox/corpus 2>/dev/null; chmod 755 /sandbox/bin /sandbox/bin/veil; chmod -R a-w /sandbox/corpus; ls -l /sandbox/corpus | head -20'
