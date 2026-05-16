import os, requests, base64, sys

def main():
    url = os.environ.get("WORD2PIC_URL", "http://127.0.0.1:9001")
    url = url.rstrip('/') + "/api/v1/generate"
    payload = {
        "prompt": "霓虹城市夜景",
        "negative_prompt": "模糊",
        "resolution": "512x512",
        "seed": 42,
        "style": "neon",
        "format": "PNG",
        "workflow": "test_z_image_turbo"
    }
    print("POST", url)
    print("payload:", payload)
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    j = r.json()
    data_url = j.get("image_base64")
    if not data_url:
        print("No image_base64 in response", j)
        sys.exit(2)
    header, b64 = data_url.split(",", 1)
    ext = "png" if "png" in header.lower() else "jpg"
    fname = f"out_image.{ext}"
    with open(fname, "wb") as f:
        f.write(base64.b64decode(b64))
    print("Saved", fname)
    print("image_name:", j.get("image_name"))
    print("metadata:", j.get("metadata"))

if __name__ == '__main__':
    main()
