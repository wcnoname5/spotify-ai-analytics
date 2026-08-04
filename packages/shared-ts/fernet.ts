// WebCrypto implementation of the Fernet token format (https://github.com/fernet/spec),
// compatible with Python's cryptography.fernet — same TOKEN_ENCRYPT_KEY, same ciphertext.
// Token: 0x80 || BE64(unix seconds) || IV(16) || AES-128-CBC(PKCS7) || HMAC-SHA256(32), base64url.
// Key: base64url(32 bytes) — first 16 = HMAC signing key, last 16 = AES encryption key.

const VERSION = 0x80;

function b64urlDecode(s: string): Uint8Array {
  const raw = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function b64urlEncode(bytes: Uint8Array): string {
  let raw = "";
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_");
}

async function importKeys(keyB64: string) {
  const key = b64urlDecode(keyB64);
  if (key.length !== 32) throw new Error("Fernet key must decode to 32 bytes");
  const signingKey = await crypto.subtle.importKey(
    "raw", key.slice(0, 16), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]
  );
  const encryptionKey = await crypto.subtle.importKey(
    "raw", key.slice(16), "AES-CBC", false, ["encrypt", "decrypt"]
  );
  return { signingKey, encryptionKey };
}

export async function fernetDecrypt(token: string, keyB64: string): Promise<string> {
  const { signingKey, encryptionKey } = await importKeys(keyB64);
  const data = b64urlDecode(token);
  // 1 version + 8 timestamp + 16 IV + >=16 ciphertext + 32 HMAC
  if (data.length < 73 || data[0] !== VERSION) throw new Error("Malformed Fernet token");
  const body = data.slice(0, data.length - 32);
  const hmac = data.slice(data.length - 32);
  const valid = await crypto.subtle.verify("HMAC", signingKey, hmac, body);
  if (!valid) throw new Error("Fernet HMAC verification failed");
  const iv = data.slice(9, 25);
  const ciphertext = data.slice(25, data.length - 32);
  const plain = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, encryptionKey, ciphertext);
  return new TextDecoder().decode(plain);
}

export async function fernetEncrypt(plaintext: string, keyB64: string): Promise<string> {
  const { signingKey, encryptionKey } = await importKeys(keyB64);
  const iv = crypto.getRandomValues(new Uint8Array(16));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-CBC", iv }, encryptionKey, new TextEncoder().encode(plaintext))
  );
  const body = new Uint8Array(25 + ciphertext.length);
  body[0] = VERSION;
  new DataView(body.buffer).setBigUint64(1, BigInt(Math.floor(Date.now() / 1000)));
  body.set(iv, 9);
  body.set(ciphertext, 25);
  const hmac = new Uint8Array(await crypto.subtle.sign("HMAC", signingKey, body));
  const out = new Uint8Array(body.length + 32);
  out.set(body);
  out.set(hmac, body.length);
  return b64urlEncode(out);
}
