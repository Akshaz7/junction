# Hologram × Codex

**Codex implements Hologram's web, 3D and iOS interfaces through scoped worker tasks.** The LEAD assigns a row with input files, contract sections and a done test; a worker reads the repo instructions, changes its allowed files and records the result in its handoff. The LEAD reruns acceptance checks and owns commits.

**Where it is set out:**

- `AGENTS.md`, “How a Codex worker gets a row,” specifies `codex exec`, folder ownership, handoff results and LEAD validation. `CLAUDE.md` and `CONTRACT.md` define the product and shared interfaces.
- `handoff/WEB.md`, `handoff/3D.md` and `handoff/IOS.md` record assignments, attempted checks and outstanding acceptance work. `handoff/WEB2.md` assigns this documentation work.
- `web/src/App.tsx::App` composes the web workspace; `web/src/viewer3d/Viewer3D.tsx::Viewer3D` implements the model viewer; `ios/Hologram/AR/ARScreen.swift::ARScreen` and `ios/Hologram/LiveSocket.swift::LiveSocket` implement the native AR screen and live connection.

**Recorded evidence:** the handoffs contain build results and explicit requests for LEAD-run browser or simulator checks. `results/fidelity/report.json` holds the recorded UI comparison outcomes; it should be read with the current WEB handoff rather than treated as blanket acceptance. There is no Codex productivity or cost benchmark in `results/`, so no such figure is claimed.

Screenshot placeholder: `docs/sponsors/img/codex.png` — LEAD to capture a scoped worker handoff beside the resulting Hologram interface, without secrets.

**Honest limits:** Codex is part of the build workflow; the application does not call Codex to answer drawing questions. The Claude-owned backend, data and engine meet the Codex-owned interfaces at `CONTRACT.md`. Pending browser, simulator and physical-device checks remain pending even when a worker's local build succeeds; the handoffs explicitly distinguish those outcomes.
