"""The local semantic model: discovery, opt-in pinned download with SHA-256 checks, consent.

Only one model is supported: ``intfloat/multilingual-e5-small`` (384 dims, MIT, 100 languages),
pinned to one Hugging Face commit. The product ships the int8 dynamic-quantized ONNX export the
model author publishes in that commit (``onnx/model_qint8_avx512_vnni.onnx``, 118 MB, vs 470 MB
fp32): the 250k-token embedding table is ~80% of the weights, so int8 is the smallest build
that keeps the full multilingual vocabulary. The quantized model also runs on arm64 CPUs
(ONNX Runtime falls back from VNNI kernels); agreement with fp32 is measured in
docs/modules/catalog/validation.md.

Layout of a model directory (``<root>/multilingual-e5-small``)::

    onnx/<model file>.onnx   onnx/tokenizer.json   manifest.json (written after verification)

A directory without ``manifest.json`` but with ``onnx/model.onnx`` + ``onnx/tokenizer.json``
(a manual ``huggingface-cli download``) is accepted as is; the encoder hashes both files into
its model identity either way.

Nothing is downloaded unless the user allowed it (``set_download_allowed`` from the API or the
``ORBIT_CATALOG_MODEL_DOWNLOAD=1`` environment switch). Downloads resume from ``.part`` files
with HTTP Range, and a file is only moved into place after its size and SHA-256 match the pinned
values; a mismatch deletes the partial file and fails the job (``model_checksum_mismatch``).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

MODEL_NAME = "multilingual-e5-small"
REPO = "intfloat/multilingual-e5-small"
# huggingface.co/api/models/intfloat/multilingual-e5-small -> "sha" (checked 2026-10-03).
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
# (repo path, bytes, sha256) from the same API call (?blobs=true, LFS sha256).
FILES = (
    ("onnx/model_qint8_avx512_vnni.onnx", 118_346_824, "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    ("onnx/tokenizer.json", 17_082_730, "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
)
PRECISION = "int8-dynamic"
DOWNLOAD_BYTES = sum(size for _, size, _ in FILES)
ENV_ALLOW = "ORBIT_CATALOG_MODEL_DOWNLOAD"
CHUNK = 1 << 20


class ModelDownloadError(RuntimeError):
    """``code`` is a stable snake_case reason shown in status (never a raw exception text)."""


def default_roots(home: str | Path | None = None) -> list[Path]:
    """Where models are looked for, in order: the catalog home, $ORBIT_HOME, the App default."""
    roots = []
    if home is not None:
        roots.append(Path(home) / "models")
    if os.environ.get("ORBIT_HOME"):
        roots.append(Path(os.environ["ORBIT_HOME"]) / "models")
    roots.append(Path.home() / "Library/Application Support/Orbit/models")
    seen, result = set(), []
    for root in roots:
        key = str(root.expanduser().resolve())
        if key not in seen:
            seen.add(key)
            result.append(Path(key))
    return result


def model_files(directory: str | Path) -> tuple[Path, Path, dict]:
    """(onnx model, tokenizer, manifest or {}) of a model directory; raises when incomplete."""
    directory = Path(directory)
    manifest = {}
    if (directory / "manifest.json").is_file():
        manifest = json.loads((directory / "manifest.json").read_text())
        model, tokenizer = directory / manifest["model_file"], directory / manifest["tokenizer_file"]
    else:
        model, tokenizer = directory / "onnx/model.onnx", directory / "onnx/tokenizer.json"
    if not model.is_file() or not tokenizer.is_file():
        raise FileNotFoundError("embedding_model_incomplete")
    for entry in manifest.get("files", []):
        if (directory / entry["path"]).stat().st_size != entry["bytes"]:
            raise FileNotFoundError("embedding_model_incomplete")
    return model, tokenizer, manifest


def discover(roots: list[Path]) -> Path | None:
    """First complete ``<root>/multilingual-e5-small`` directory (stat calls only, no hashing)."""
    for root in roots:
        candidate = root / MODEL_NAME
        try:
            model_files(candidate)
        except (OSError, ValueError, KeyError):
            continue
        return candidate
    return None


def download_allowed(root: Path) -> bool:
    if os.environ.get(ENV_ALLOW, "").lower() in ("1", "true", "yes"):
        return True
    try:
        return bool(json.loads((root / "download.json").read_text()).get("allowed"))
    except (OSError, ValueError):
        return False


def set_download_allowed(root: Path, allowed: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "download.json.tmp"
    tmp.write_text(json.dumps({"allowed": bool(allowed), "model": REPO, "revision": REVISION,
                               "bytes": DOWNLOAD_BYTES, "at": int(time.time() * 1000)}))
    tmp.replace(root / "download.json")


def _sha256(path: Path) -> hashlib._Hash:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest


def _default_open(url: str, headers: dict):
    # huggingface.co answers /resolve/ with a redirect to its LFS/Xet CDN host; the host is not
    # trusted for integrity, the pinned SHA-256 is.
    if urlsplit(url).scheme != "https":
        raise ModelDownloadError("model_url_not_https")
    return build_opener().open(Request(url, headers={"User-Agent": "orbit-catalog", **headers}), timeout=60)


def download(root: Path, *, opener=_default_open, cancelled=lambda: False, progress=None,
             files=FILES, base_url=f"https://huggingface.co/{REPO}/resolve/{REVISION}/") -> Path:
    """Fetch the pinned files into ``root/multilingual-e5-small``; resumable and verified.

    ``opener(url, headers)`` returns a context-managed response with ``read(n)`` and ``status``
    (urllib by default). ``progress(done_bytes, total_bytes)`` is called after each block.
    Returns the model directory once every file matches its pinned size and SHA-256.
    """
    target = root / MODEL_NAME
    total = sum(size for _, size, _ in files)
    done = 0
    for path, size, sha in files:
        final = target / path
        if final.is_file() and final.stat().st_size == size and _sha256(final).hexdigest() == sha:
            done += size
            continue
        final.parent.mkdir(parents=True, exist_ok=True)
        part = final.with_name(final.name + ".part")
        have = part.stat().st_size if part.is_file() else 0
        if have > size:
            part.unlink()
            have = 0
        digest = _sha256(part) if have else hashlib.sha256()
        if have < size:
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                with opener(base_url + path, headers) as response:
                    if have and getattr(response, "status", 206) != 206:
                        # Server ignored the Range header: start over from byte 0.
                        have, digest = 0, hashlib.sha256()
                        part.unlink(missing_ok=True)
                    with part.open("ab") as out:
                        while block := response.read(CHUNK):
                            if cancelled():
                                raise ModelDownloadError("model_download_cancelled")
                            have += len(block)
                            if have > size:
                                break
                            out.write(block)
                            digest.update(block)
                            if progress:
                                progress(done + have, total)
            except HTTPError as exc:
                raise ModelDownloadError(f"model_http_{exc.code}") from None
            except (URLError, TimeoutError, ConnectionError) as exc:
                raise ModelDownloadError("model_network_error") from exc
        if have != size or digest.hexdigest() != sha:
            part.unlink(missing_ok=True)
            raise ModelDownloadError("model_checksum_mismatch")
        part.replace(final)
        done += size
    manifest = {"name": MODEL_NAME, "repo": REPO, "revision": REVISION, "precision": PRECISION,
                "model_file": files[0][0], "tokenizer_file": files[1][0], "license": "MIT",
                "files": [{"path": p, "bytes": s, "sha256": h} for p, s, h in files],
                "verified_at": int(time.time() * 1000)}
    (target / "manifest.json.tmp").write_text(json.dumps(manifest, indent=2))
    (target / "manifest.json.tmp").replace(target / "manifest.json")
    return target
