"""Detached authenticated provenance for code without changing its bytes."""
from __future__ import annotations
import hashlib, hmac, json

def create_code_manifest(code: str, session_id: str, secret: str | bytes, chunk_lines: int = 50) -> dict:
    key = secret.encode() if isinstance(secret, str) else secret
    lines = code.splitlines(keepends=True)
    chunks = ["".join(lines[i:i+chunk_lines]) for i in range(0, len(lines), chunk_lines)] or [""]
    manifest = {
        "version": 1,
        "session_tag": hmac.new(key, b"XRF/code-session/"+session_id.encode(), hashlib.sha256).hexdigest()[:16],
        "chunk_lines": chunk_lines,
        "content_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "chunk_sha256": [hashlib.sha256(x.encode()).hexdigest() for x in chunks],
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["mac"] = hmac.new(key, b"XRF/code-manifest/"+canonical, hashlib.sha256).hexdigest()
    return manifest

def verify_code_manifest(code: str, manifest: dict, secret: str | bytes) -> dict:
    key = secret.encode() if isinstance(secret, str) else secret
    unsigned = {k:v for k,v in manifest.items() if k != "mac"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    authentic = hmac.compare_digest(str(manifest.get("mac", "")), hmac.new(key,b"XRF/code-manifest/"+canonical,hashlib.sha256).hexdigest())
    lines=code.splitlines(keepends=True); size=int(manifest.get("chunk_lines",50)); chunks=["".join(lines[i:i+size]) for i in range(0,len(lines),size)] or [""]
    hashes=[hashlib.sha256(x.encode()).hexdigest() for x in chunks]; expected=manifest.get("chunk_sha256",[])
    matching=sum(a==b for a,b in zip(hashes,expected))
    return {"manifest_authentic":authentic,"exact_content":hashlib.sha256(code.encode()).hexdigest()==manifest.get("content_sha256"),"matching_chunks":matching,"total_expected_chunks":len(expected),"changed_chunks":[i for i,(a,b) in enumerate(zip(hashes,expected)) if a!=b]}
