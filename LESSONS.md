# LESSONS

What worked and what failed. One or two lines per entry.
- Bathtubs/showers are badly under-detected by the CubiCasa official baseline (0/3 on colorful-11397); showers have no class and live under kind bathtub with props.includes_shower.
- Router kind/scope labels were written by ENGINE after reading the test templates: the 97.4% is an upper bound; the type label (from the dataset) is independent at 99.0%.
- E-03's colorful-11397 test fixture was hand-annotated by ENGINE by eye (VISION's 12 windows + one split strip = 13); it tests the solver, not vision accuracy.
- Loading .env into os.environ at import leaks keys across test suites: load it as a dict and skip secrets (server/config.py).
- Vision baseline (V-04): count questions on raster plans are exact only 52% of the time; windows 30%, showers+bathtubs 11.5%. Rooms with readable labels do much better (balcony 88%, kitchen 75%).
- The full question set references 4,788 of the 5,000 CubiCasa5K drawings: only ~212 are clean for training. Fine-tuning needs external or synthetic data.

E-19 pass 1 (ENGINE, 14 Nov): plan-map counts of "storeys" = number of pages; room-subtype questions (bedroom, kitchen, WC room, bathroom, balcony) must filter by props.room_type instead of counting all rooms; a room number beats the shared room name; apartments = DXF items with role=unit; near-zero IfcSpace areas are broken quantities (abstain). sample200 25.7% -> 57.2% (sample200-r1 -> r8; scorer tolerance moved 1% -> 2% per the dataset README).
- 14:15 CubiCasa counts: the plan map does not overcount windows/doors/sinks, so reconcile with min(plan, vision); use vision only for showers/bathtubs. (ENGINE-ACC, sample200)
- Multi-kind counts: Parsed.kinds list (kind = first, str); _solve_multi merges per-kind answers. Advisor cards now carry severity + checked; hide commands go through entrance.py (front/outer door = detected entrance, not every door).
- Judge-set shapes (floor compare, 'wider than N', waste take-off, named rooms, rule check) are code in engine/analytics.py, hooked before the exit finder; results/qa/run_judge.py grades 43 hand-gold questions (22/43 -> 41/43 correct).
- 22:13 Manual 3D edits were sent over /ws without chat_id, so the server relayed but never stored them and the chat could not undo them (and they leaked into every chat on that doc). Anything that should be part of a chat's state must carry chat_id.
