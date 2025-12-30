import random
import struct
import zlib


def _png_chunk(tag, data):
    length = struct.pack("!I", len(data))
    crc = struct.pack("!I", zlib.crc32(tag + data) & 0xffffffff)
    return length + tag + data + crc


def random_png_image(size, image_mb):
    parts = size.lower().split("x")
    if len(parts) == 2:
        width, height = int(parts[0]), int(parts[1])
    else:
        target = image_mb * 1024 * 1024
        width = 1024
        row_bytes = width * 3 + 1
        height = max(1, target // row_bytes)
        if height * row_bytes < target:
            height += 1

    raw = bytearray(height * (width * 3 + 1))
    offset = 0
    for _ in range(height):
        raw[offset] = 0
        offset += 1
        for i in range(width * 3):
            raw[offset + i] = random.getrandbits(8)
        offset += width * 3

    compressed = zlib.compress(bytes(raw), level=6)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate a random PNG image")
    parser.add_argument("--output", default="random.png", help="Output PNG path")
    parser.add_argument("--image-size", default="", help="Image size WxH, overrides --image-mb")
    parser.add_argument("--image-mb", type=int, default=10, help="Target image size in MB")
    args = parser.parse_args()

    size = args.image_size or f"{args.image_mb}MB"
    payload = random_png_image(size, args.image_mb)
    with open(args.output, "wb") as f:
        f.write(payload)
    print(f"Wrote {args.output} ({len(payload)} bytes)")


if __name__ == "__main__":
    main()
