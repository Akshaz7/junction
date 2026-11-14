import modal
app = modal.App("junction-ping")
@app.function()
def ping():
    return "pong"
@app.local_entrypoint()
def main():
    print("result", ping.remote())
