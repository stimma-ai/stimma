"""Generate deterministic USTAR/gzip packages and adversarial archive fixtures."""
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, body, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mode = 0o644
            info.size = len(body)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "../../outside"
            tar.addfile(info, io.BytesIO(body))
    return output.getvalue()


def main():
    with tempfile.TemporaryDirectory(prefix="stimma-ui-packages-") as directory:
        root = Path(directory)
        regular = tarfile.REGTYPE
        base = [("index.html", b"first interface", regular), ("assets/app.js", b"console.log('first')", regular)]

        def write(name, entries=None, raw=None, expanded=None):
            entries = entries if entries is not None else base
            tar = archive(entries) if raw is None else raw
            compressed = gzip.compress(tar, mtime=0)
            if name == "truncated":
                compressed = compressed[:-4]
            if name == "concatenated":
                compressed += gzip.compress(b"extra", mtime=0)
            manifest = dict(formatVersion=1, hash=hashlib.sha256(compressed).hexdigest(), bytes=len(compressed),
                            unpackedBytes=sum(len(body) for _, body, _ in entries) if expanded is None else expanded,
                            bridgeVersion=1, apiVersion=1, entrypoint="index.html")
            (root / (name + ".tar.gz")).write_bytes(compressed)
            (root / (name + ".json")).write_text(json.dumps(manifest))

        write("one")
        write("two", [("index.html", b"other interface", regular), ("assets/app.js", b"console.log('other')", regular)])
        write("three", [("index.html", b"third interface", regular), ("assets/app.js", b"console.log('third')", regular)])
        for name, path, kind in [
            ("symlink", "link", tarfile.SYMTYPE), ("hardlink", "link", tarfile.LNKTYPE),
            ("absolute", "/outside", regular), ("dotdot", "../outside", regular),
            ("duplicate", "index.html", regular), ("case-collision", "INDEX.HTML", regular),
            ("parent-file", "assets", regular), ("special", "fifo", tarfile.FIFOTYPE),
            ("directory", "folder", tarfile.DIRTYPE),
        ]:
            write(name, base + [(path, b"", kind)])
        broken = bytearray(archive(base)); broken[0] ^= 1
        write("checksum", raw=broken)
        broken = bytearray(archive(base)); broken[263] = ord("1")
        write("bad-version", raw=broken)
        write("truncated")
        write("concatenated")
        write("missing-index", [("other.html", b"not an entrypoint", regular)])
        write("expanded-bound", expanded=1)
        write("too-many", base + [("files/" + str(i), b"", regular) for i in range(10000)])
        subprocess.run([sys.argv[1], str(root)], check=True, timeout=60)


if __name__ == "__main__":
    main()
