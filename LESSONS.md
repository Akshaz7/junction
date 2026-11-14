# LESSONS

What worked and what failed. One or two lines per entry.
- Bathtubs/showers are badly under-detected by the CubiCasa official baseline (0/3 on colorful-11397); showers have no class and live under kind bathtub with props.includes_shower.
- Router kind/scope labels were written by ENGINE after reading the test templates: the 97.4% is an upper bound; the type label (from the dataset) is independent at 99.0%.
- E-03's colorful-11397 test fixture was hand-annotated by ENGINE by eye (VISION's 12 windows + one split strip = 13); it tests the solver, not vision accuracy.
- Loading .env into os.environ at import leaks keys across test suites: load it as a dict and skip secrets (server/config.py).
