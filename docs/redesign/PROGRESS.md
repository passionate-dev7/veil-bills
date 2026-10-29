# Redesign progress
- [x] Step0: before-1440/768/390.png exist (from pre-redesign web/index.html)
- [x] DIRECTIONS.md (A chosen), DESIGN.md, web/veil.css extracted. commit done
- [x] lane1 markup done in /tmp/veil-ui (deepseek, pass attempt 1, console clean)
- [ ] lane2 css (task /tmp/lane2.txt), then copy index.html+veil.css back to web/
- Step 3: new web/index.html + veil.css wired to real run.json; slop-check PASS; 36 tests pass; tools/shots.py now lays out <500px widths in a true-width iframe (headless Chrome min window is 500px, so earlier 390 shots were cropped 500px layouts).
