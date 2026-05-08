/**
 * GitChain GitHub Action script
 *
 * Runs on every git push as a CI step. Reads commit metadata from the
 * GitHub environment, builds + signs the transaction payload, and POSTs
 * it to the team's GitChain node.
 *
 * Dependencies (installed by the action):
 *   tweetnacl     — Ed25519 sign/verify (same algorithm as PyNaCl)
 *
 * Environment variables (from GitHub Secrets):
 *   GITCHAIN_PRIVATE_KEY  — 64-char hex Ed25519 private key
 *   GITCHAIN_NODE_URL     — e.g. http://192.168.1.10:8000
 *
 * GitHub-provided environment variables (automatic):
 *   GITHUB_SHA            — commit hash
 *   GITHUB_ACTOR          — GitHub username of the pusher
 *   GITHUB_REPOSITORY     — org/repo
 *   GITHUB_REF_NAME       — branch name
 */

const nacl = require('tweetnacl');                    // Ed25519 sign/verify library (matches PyNaCl on the node)
const { execSync } = require('child_process');        // lets us run shell commands like git show
const https = require('https');                       // for POSTing to https:// node URLs
const http = require('http');                         // for POSTing to http:// node URLs (ngrok, local)
const crypto = require('crypto');                     // Node.js built-in SHA-256 hashing


// ---------------------------------------------------------------------------
// 1. Read inputs
// ---------------------------------------------------------------------------

const privateKeyHex = process.env.GITCHAIN_PRIVATE_KEY;          // 64-char hex Ed25519 private key from GitHub Secrets
const nodeUrl       = process.env.GITCHAIN_NODE_URL;              // URL of the running GitChain node (e.g. ngrok URL)
const commitHash    = process.env.GITHUB_SHA;                     // full 40-char git SHA of the commit that triggered this push
const repo          = process.env.GITHUB_REPOSITORY;              // "org/repo" string e.g. "RedSkullX3/testgitchian"
const branch        = process.env.GITHUB_REF_NAME || 'unknown';  // branch name e.g. "main"; fallback if not set
const author        = process.env.GITHUB_ACTOR    || 'unknown';  // GitHub username of the person who pushed; fallback if not set
const timestamp     = Math.floor(Date.now() / 1000);              // current unix time as integer seconds (Math.floor matches Python's int(timestamp))

if (!privateKeyHex || !nodeUrl || !commitHash || !repo) {         // guard: all four are required to proceed
  console.error('Missing required environment variables.');        // print which variables are missing
  console.error('Required: GITCHAIN_PRIVATE_KEY, GITCHAIN_NODE_URL, GITHUB_SHA, GITHUB_REPOSITORY');
  process.exit(1);                                                 // exit with error code so the Action step fails visibly
}

// ---------------------------------------------------------------------------
// 2. Get diff summary from git
// ---------------------------------------------------------------------------

let diffSummary = 'unknown';                                                        // default if git command fails
let diffHash = '';                                                                   // default empty string if diff cannot be computed
try {
  const stat = execSync('git show --stat HEAD', { encoding: 'utf8' });              // run git show --stat to get file-change summary
  // Extract the summary line: "3 files changed, 42 insertions(+), 7 deletions(-)"
  const match = stat.match(/(\d+ files? changed.*)/);                               // regex to find the summary line in the --stat output
  if (match) diffSummary = match[1].trim();                                         // store just the summary line, trimming whitespace
} catch (e) {
  console.warn('Warning: could not get diff summary:', e.message);                  // non-fatal: record "unknown" and continue
}
try {
  const fullDiff = execSync('git show -p HEAD', { encoding: 'utf8' });              // get the full patch (every added/removed line) as a string
  diffHash = crypto.createHash('sha256').update(fullDiff).digest('hex');            // SHA-256 of the full patch — binds exact line changes to this transaction
} catch (e) {
  console.warn('Warning: could not compute diff hash:', e.message);                 // non-fatal: diff_hash stays "" and is stored as empty string
}

// ---------------------------------------------------------------------------
// 3. Derive public key from private key
// ---------------------------------------------------------------------------

const privateKeyBytes = Buffer.from(privateKeyHex, 'hex');                          // decode the hex private key string into raw bytes

// tweetnacl expects a 64-byte seed+pubkey buffer; PyNaCl stores only the 32-byte seed.
// If we only have 32 bytes, generate the full keypair from the seed.
let keyPair;
if (privateKeyBytes.length === 32) {
  keyPair = nacl.sign.keyPair.fromSeed(privateKeyBytes);                            // PyNaCl-generated key: 32-byte seed → derive full 64-byte keypair
} else if (privateKeyBytes.length === 64) {
  keyPair = nacl.sign.keyPair.fromSecretKey(privateKeyBytes);                       // already a full 64-byte tweetnacl secret key
} else {
  console.error('Invalid private key length:', privateKeyBytes.length);             // unexpected length — key is corrupt or wrong format
  process.exit(1);                                                                   // exit: cannot sign without a valid key
}

const ownerPubkey = Buffer.from(keyPair.publicKey).toString('hex');                 // derive the 32-byte public key and hex-encode it for the transaction

// ---------------------------------------------------------------------------
// 4. Build and hash the payload
// ---------------------------------------------------------------------------

const payloadFields = {               // the 8 fields that will be hashed and signed
  author:        author,              // GitHub username — who pushed
  branch:        branch,              // branch name — which branch was pushed to
  commit_hash:   commitHash,          // git SHA — which commit this records
  diff_hash:     diffHash,            // SHA-256 of full patch — proves exact line changes
  diff_summary:  diffSummary,         // human-readable "N files changed" summary
  owner_pubkey:  ownerPubkey,         // CI bot's public key — used for signature verification
  repo:          repo,                // repository — which project this belongs to
  timestamp:     timestamp,           // unix time integer — when this was pushed
};

// Deterministic JSON — sorted keys, no spaces.
// Matches Python's json.dumps(sort_keys=True, separators=(',', ':'))
// Timestamp is already an integer from Math.floor, matching Python's int(timestamp) in compute_payload_hash().
const canonicalPayload = JSON.stringify(
  Object.keys(payloadFields).sort().reduce((acc, k) => { acc[k] = payloadFields[k]; return acc; }, {}),
);                                    // sort keys alphabetically so the JSON string is identical regardless of insertion order

const payloadHash = crypto.createHash('sha256').update(canonicalPayload).digest('hex'); // SHA-256 of the canonical JSON — single 64-char fingerprint of all 8 fields

// ---------------------------------------------------------------------------
// 5. Sign the payload hash with Ed25519
// ---------------------------------------------------------------------------

// Sign the UTF-8 bytes of the hex hash string (matches signer.py)
// Buffer.from(string) encodes as UTF-8 and is a native Uint8Array subclass —
// avoids tweetnacl-util compatibility issues with checkArrayTypes.
const signature = Buffer.from(
  nacl.sign.detached(Buffer.from(payloadHash), keyPair.secretKey)   // Ed25519 detached sign: produces 64-byte signature without prepending the message
).toString('hex');                                                   // hex-encode the 64-byte signature for JSON transport

// ---------------------------------------------------------------------------
// 6. Build the transaction object
// ---------------------------------------------------------------------------

const transaction = {               // all 10 fields POSTed to /transaction
  commit_hash:  commitHash,         // git SHA identifying the commit
  owner_pubkey: ownerPubkey,        // CI bot public key — node uses this to verify the signature
  author:       author,             // GitHub username of the developer who pushed
  repo:         repo,               // "org/repo" repository identifier
  branch:       branch,             // branch that was pushed to
  timestamp:    timestamp,          // unix time as integer
  diff_summary: diffSummary,        // "N files changed" human-readable string
  diff_hash:    diffHash,           // SHA-256 of the full git patch — line-level authorship proof
  payload_hash: payloadHash,        // SHA-256 of the 8 fields above — node recomputes this to detect tampering
  signature:    signature,          // Ed25519 signature of payload_hash — proves this came from the CI bot
};

console.log('GitChain transaction:');                               // print summary to GitHub Actions log
console.log('  commit:', commitHash.slice(0, 12) + '...');         // truncated commit SHA for readability
console.log('  repo:  ', repo);                                     // repository name
console.log('  branch:', branch);                                   // branch name
console.log('  author:', author);                                   // GitHub username of pusher

// ---------------------------------------------------------------------------
// 7. POST to node with retry (exponential backoff)
// ---------------------------------------------------------------------------

const MAX_RETRIES = 3;                                              // try up to 3 times before giving up

function post(url, body) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);                                                          // parse the node URL into hostname, port, path
    const transport = parsed.protocol === 'https:' ? https : http;                       // pick https or http module based on URL scheme
    const data = JSON.stringify(body);                                                    // serialise the transaction object to a JSON string for the request body

    const req = transport.request(
      {
        hostname: parsed.hostname,                                                        // e.g. "abc123.ngrok.io" or "192.168.1.10"
        port:     parsed.port || (parsed.protocol === 'https:' ? 443 : 80),              // use port from URL, or default 443/80
        path:     parsed.pathname,                                                        // "/transaction"
        method:   'POST',                                                                 // HTTP POST to submit the transaction
        headers:  {
          'Content-Type':   'application/json',                                          // tell FastAPI to parse body as JSON
          'Content-Length': Buffer.byteLength(data),                                     // required header so server knows when body ends
        },
      },
      (res) => {
        let responseBody = '';                                                            // accumulate response chunks
        res.on('data', chunk => { responseBody += chunk; });                             // each chunk arrives separately; append it
        res.on('end', () => {                                                            // all chunks received — response is complete
          if (res.statusCode === 201 || res.statusCode === 409) {
            // 201 = accepted, 409 = already recorded (both are fine)
            resolve({ status: res.statusCode, body: responseBody });                     // success: resolve the promise with status + body
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${responseBody}`));                // any other status (400, 500 etc.) is an error — reject to trigger retry
          }
        });
      }
    );

    req.on('error', reject);                                                             // network-level error (connection refused, DNS failure) — reject to trigger retry
    req.write(data);                                                                     // send the JSON body
    req.end();                                                                           // signal that the request body is complete
  });
}

async function submitWithRetry() {
  const endpoint = nodeUrl.replace(/\/$/, '') + '/transaction';    // strip trailing slash then append /transaction path

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {       // loop up to MAX_RETRIES times
    try {
      const result = await post(endpoint, transaction);             // attempt the POST
      if (result.status === 409) {
        console.log('Commit already on-chain — skipping.');         // 409 means this commit was already recorded; not an error
      } else {
        console.log('✓ Transaction accepted by GitChain node.');    // 201 means the node accepted and queued it in the mempool
      }
      return;                                                        // success — exit the retry loop
    } catch (err) {
      console.warn(`Attempt ${attempt}/${MAX_RETRIES} failed: ${err.message}`);  // log which attempt failed and why
      if (attempt < MAX_RETRIES) {
        const delay = Math.pow(2, attempt) * 500;   // 1s, 2s, 4s   // exponential backoff: 500ms * 2^attempt
        console.log(`Retrying in ${delay}ms...`);                    // inform the Actions log of the wait
        await new Promise(r => setTimeout(r, delay));                // wait before next attempt
      } else {
        console.error('All retry attempts exhausted. GitChain node may be offline.');
        // Do NOT fail the CI build — contribution recording is best-effort
        // The commit is still pushed to GitHub; it will be recorded when node is back.
        process.exit(0);                                             // exit 0 so the CI build passes even if GitChain is unreachable
      }
    }
  }
}

submitWithRetry();                                                   // entry point — start the submit process
