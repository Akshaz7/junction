# Deploy (stub, row S-05)

- API + live sync: one container (`deploy/Dockerfile`) on **Aiven Runtime**, EU region.
- Database: **Aiven PostgreSQL**, EU region. Set `DATABASE_URL` from the Aiven service URI.
- Set `RATE_LIMIT=1` (30 req/min/IP, in-memory; default in the image).
- Web on Vercel; point it at the Runtime URL.
- Build: `scripts/heavy.sh docker build -f deploy/Dockerfile -t hologram-api .`
