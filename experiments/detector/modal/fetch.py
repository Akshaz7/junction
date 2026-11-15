"""Download the public Junction dataset zip straight onto a Modal volume (nothing downloaded to the laptop).
   modal run --detach fetch.py"""
import modal
app = modal.App("junction-det-fetch")
vol = modal.Volume.from_name("junction-ds", create_if_missing=True)
URL = "https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip"

@app.function(image=modal.Image.debian_slim().apt_install("curl", "unzip"), volumes={"/ds": vol}, timeout=3600,
              cpu=4)
def fetch():
    import subprocess, os, collections, pathlib
    subprocess.run(["curl", "-sSfL", "--retry", "3", "-o", "/tmp/ds.zip", URL], check=True)
    print("zip bytes", os.path.getsize("/tmp/ds.zip"), flush=True)
    subprocess.run(["unzip", "-q", "-o", "/tmp/ds.zip", "-d", "/ds/full"], check=True)
    c = collections.Counter()
    for p in pathlib.Path("/ds/full").rglob("*"):
        if p.is_file():
            parts = p.relative_to("/ds/full").parts
            src = parts[-2] if len(parts) >= 2 else "."
            c[(parts[1] if len(parts) > 2 and parts[0] == "data" else src, p.suffix.lower())] += 1
    vol.commit()
    for k, v in sorted(c.items()):
        print(k, v)
    return dict((f"{a}{b}", v) for (a, b), v in c.items())

@app.local_entrypoint()
def main():
    print(fetch.remote())
