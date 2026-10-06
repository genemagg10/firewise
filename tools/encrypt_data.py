#!/usr/bin/env python3
"""Encrypt the private residents payload for publishing.

AES-256-GCM, key = PBKDF2-HMAC-SHA256(password, random 16-byte salt, 600,000 iterations), random 12-byte IV.
The browser (assets/firewise.js) derives the same key with WebCrypto and decrypts in-page.

The password is NEVER stored in the repo. It is read from the FIREWISE_PASSWORD environment variable,
or prompted for interactively.

  FIREWISE_PASSWORD='...' python3 tools/encrypt_data.py      # normally called by tools/build_data.py
"""
import base64, getpass, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib

ITERATIONS = 600_000
FORMAT = "firewise-enc-v1"

def get_password(confirm=True):
    pw = os.environ.get("FIREWISE_PASSWORD")
    if pw: return pw
    if not sys.stdin.isatty():
        sys.exit("ERROR: set FIREWISE_PASSWORD (or run interactively to be prompted). Refusing to publish unencrypted data.")
    pw = getpass.getpass("Site password: ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        sys.exit("ERROR: passwords did not match")
    if len(pw) < 10: sys.exit("ERROR: use a password of at least 10 characters")
    return pw

def encrypt_payload(obj, password):
    b64 = lambda b: base64.b64encode(b).decode()
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=32)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, separators=(",", ":")).encode("utf-8"), None)  # ciphertext || 16-byte tag
    return {"format": FORMAT, "cipher": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS,
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}

def decrypt_payload(env, password):
    d = lambda s: base64.b64decode(s)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), d(env["salt"]), env["iterations"], dklen=32)
    return json.loads(AESGCM(key).decrypt(d(env["iv"]), d(env["ciphertext"]), None))

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "data", "residents.json")
    pw = get_password()
    env = encrypt_payload({"residents": json.load(open(src))}, pw)
    json.dump(env, open(os.path.join(root, "data", "residents.enc.json"), "w"))
    print("wrote data/residents.enc.json")
