# LESSONS

What worked and what failed. One or two lines per entry.
- Bathtubs/showers are badly under-detected by the CubiCasa official baseline (0/3 on colorful-11397); showers have no class and live under kind bathtub with props.includes_shower.
- Router kind/scope labels were written by ENGINE after reading the test templates: the 97.4% is an upper bound; the type label (from the dataset) is independent at 99.0%.
- E-03's colorful-11397 test fixture was hand-annotated by ENGINE by eye (VISION's 12 windows + one split strip = 13); it tests the solver, not vision accuracy.
- Loading .env into os.environ at import leaks keys across test suites: load it as a dict and skip secrets (server/config.py).
- Vision baseline (V-04): count questions on raster plans are exact only 52% of the time; windows 30%, showers+bathtubs 11.5%. Rooms with readable labels do much better (balcony 88%, kitchen 75%).
- The full question set references 4,788 of the 5,000 CubiCasa5K drawings: only ~212 are clean for training. Fine-tuning needs external or synthetic data.

E-19 pass 1 (ENGINE, 14 Nov): plan-map counts of "storeys" = number of pages; room-subtype questions (bedroom, kitchen, WC room, bathroom, balcony) must filter by props.room_type instead of counting all rooms; a room number beats the shared room name; apartments = DXF items with role=unit; near-zero IfcSpace areas are broken quantities (abstain). sample200 25.7% -> 57.2% (sample200-r1 -> r8; scorer tolerance moved 1% -> 2% per the dataset README).
