#!/usr/bin/env bash
# Parallel resumable download of CubiCasa5K (Zenodo 2613548, CC BY-NC-SA 4.0). Zenodo throttles per connection (~60 KB/s), so 24 range chunks.
# Re-run to resume. Output: data/cubicasa5k/cubicasa5k.zip
cd "$(dirname "$0")/../data/cubicasa5k" || exit 1
U=https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content
TOTAL=5469495706; N=24; CH=$(( (TOTAL + N - 1) / N ))
mkdir -p parts
dl() { i=$1; s=$((i*CH)); e=$((s+CH-1)); [ $e -ge $TOTAL ] && e=$((TOTAL-1)); want=$((e-s+1))
  for try in $(seq 1 200); do
    have=$(stat -f%z parts/p$i 2>/dev/null || echo 0); [ "$have" -ge "$want" ] && return 0
    curl -sL -r $((s+have))-$e --max-time 600 $U >> parts/p$i
  done; }
for i in $(seq 0 $((N-1))); do dl $i & done; wait
ok=1; for i in $(seq 0 $((N-1))); do :; done
cat $(for i in $(seq 0 $((N-1))); do echo parts/p$i; done) > cubicasa5k.zip && echo "ASSEMBLED $(stat -f%z cubicasa5k.zip)"
