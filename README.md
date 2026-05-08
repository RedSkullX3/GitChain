# GitChain — Decentralized Git Contribution Verifier

GitChain is a permissionless blockchain where every `git push` is permanently recorded as a cryptographically signed transaction. It proves that a commit existed at a specific time and was authored by a specific developer — including the exact lines changed — even if someone later force-pushes or rewrites history on GitHub.

---

DISCLAIMER: There is a small difference between a node that you as admin will install, if you have understood it clearly then the first/main node is required to be active in order for the whole thing to run, but if you wish for the GITHUB CI to push it directly to the second system as well which would solve the problem then you can run ngrok in the second system and copy the server link and add a GITHUB secret with the name GITCHAIN_NODE_URL_1 and also add another line (do not delete only add it below the normal one) to .github/workflows/gitchain.yml file which is uploaded to the github repository using gitchain, which is as follows,

- name: Log commit to GitChain 2
        run: node gitchain-submit.js
        working-directory: gitchain/github-action
        env:
          GITCHAIN_PRIVATE_KEY: ${{ secrets.GITCHAIN_PRIVATE_KEY }}
          GITCHAIN_NODE_URL:    ${{ secrets.GITCHAIN_NODE_URL_1 }}
          GITHUB_SHA:           ${{ github.sha }}
          GITHUB_ACTOR:         ${{ github.actor }}
          GITHUB_REPOSITORY:    ${{ github.repository }}
          GITHUB_REF_NAME:      ${{ github.ref_name }}

This will sign using the same key but also send a direct transaction to the second system via ngrok.

---
Sometimes the .github folder maybe hidden as any folder named like that is usually hidden in Linux based Distros.

(Windows Users): Find the setting that unhides hidden files
(Linux users): If you are using some app like "Files" as explorer, you can press Ctrl+h to show all hidden files. 

VS CODE should always show all files including the hidden one.

## Requirements

### System Requirements
- Python 3.11 or higher
- Node.js 18 or higher (only needed for the GitHub Action)
- A machine on a LAN if you want multi-node mDNS discovery (or use `--peer` for manual connection)

### Python Packages

Install everything with:
```bash
pip install -e .
```
It may not allow you to install then use : pip install -e . --break-system-packages

Or install manually:
```bash
pip install pynacl>=1.5.0 fastapi>=0.110.0 uvicorn>=0.29.0 zeroconf>=0.131.0 click>=8.1.0
```

For running tests, also install:
```bash
pip install pytest>=8.0.0 pytest-asyncio>=1.0.0 httpx>=0.27.0
```


### Node.js Packages (GitHub Action only)
```bash
cd gitchain/github-action
npm install tweetnacl
```

---

## Quick Start — Running a Single Node

### Step 1: Install the package
```bash
cd /path/to/GitChain
pip install -e .
```
It may not allow you to install then use : pip install -e . --break-system-packages

### Step 2: Generate your developer keypair
```bash
gitchain keygen --name "Your Name" --email "you@yourcompany.com"
```
This creates two files:
- `you@yourcompany.com.private.key` — keep this secret, never commit it
- `you@yourcompany.com.public.key` — safe to share, automatically added to `gitchain-registry.json`

### Step 3: Start the node
```bash
gitchain node start
```

The node starts with these defaults:
- P2P port: `6331` (listens for other GitChain nodes)
- API port: `8000` (REST API + dashboard)
- Difficulty: `3` (leading zeros required for PoW)
- Chain file: `chain.json` (where the blockchain is saved)
- mDNS: enabled (auto-discovers other nodes on your LAN)

Open your browser at `http://127.0.0.1:8000/dashboard` to see the live dashboard.

### Step 4: Verify a commit is on-chain
```bash
gitchain verify <commit-sha>
```

### Step 5: Check node status
```bash
gitchain status
```



### Manual Peer Connection
Use `--no-mdns` and `--peer` to connect manually:

**Machine A (IP: 192.168.1.10):**
```bash
gitchain node start --no-mdns --data chain-a.json
```

**Machine B:**
```bash
gitchain node start --no-mdns --peer 192.168.1.10:6331 --data chain-b.json
```
                                     machine a ip addr:6331
### Advanced Options
```bash
gitchain node start \
  --port 6331 \          # P2P TCP port
  --api-port 8000 \      # REST API port
  --difficulty 3 \       # PoW difficulty (3 = ~0.1-2s per block)
  --data chain.json \    # Blockchain persistence file
  --no-mdns \            # Disable auto-discovery (use --peer instead) (WARNING: WE TRIED TO DO AUTO DISCOVERY BUT IT DOES NOT WORK SO WE NOW ALWAYS USE THIS )
  --peer host:port       # Connect to specific peer on startup (repeatable)
```

---

## GitHub Action Setup

This is what makes GitChain automatic, every `git push` to your repository records the commit on the blockchain without any manual steps.

### Step 1: Generate a keypair for CI (if not done already)
```bash
gitchain keygen --name "CI Bot" --email "ci@yourcompany.com"
```

### Step 2: Add GitHub Secrets
In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Value |
| `GITCHAIN_PRIVATE_KEY` | Contents of `ci@yourcompany.com.private.key` |
| `GITCHAIN_NODE_URL` | URL of your running GitChain node, e.g. `http://192.168.1.10:8000` |

Your node must be reachable from GitHub's Action runners.
- Use ngrok : `ngrok http 8000`

### Step 3: Commit the public key registry
```bash
git add gitchain-registry.json
git commit -m "Add CI bot public key to GitChain registry"
git push
```

### Step 4: Add the workflow file
The file `.github/workflows/gitchain.yml` is already in this repo. It runs automatically on every push. If you need to add it to another repo, copy these files:
- `.github/workflows/gitchain.yml`
- `gitchain/github-action/gitchain-submit.js`
- `gitchain/github-action/action.yml`

### Step 5: Test it
Make a commit and push. In your repository's **Actions** tab you will see the `GitChain Submit` workflow run. After it completes, verify the commit appeared on-chain:
```bash
gitchain verify <your-commit-sha>
```

Or check the dashboard at `http://your-node:8000/dashboard`.

---

## REST API Reference

Your node exposes a REST API at `http://127.0.0.1:8000`. Interactive docs are at `http://127.0.0.1:8000/docs`.


### Example: Verify a commit
```bash
curl http://127.0.0.1:8000/verify/abc123def456...
```
Returns:
```json
{
  "commit_hash": "abc123...",
  "on_chain": true,
  "block_index": 4,
  "transaction": {
    "author": "alice",
    "repo": "org/repo",
    "branch": "main",
    "diff_summary": "3 files changed, +120 -40",
    "diff_hash": "e3b0c44298fc1c149afb...",
    ...
  },
  "message": "Commit is permanently recorded on-chain"
}
```

---

## Proving Who Wrote Which Lines

Every transaction stores a `diff_hash` — the SHA-256 of the full output of `git show -p HEAD`. This cryptographically binds the exact line-by-line changes to the on-chain record. The hash is inside the Ed25519-signed payload, so it cannot be altered after the fact.

### How to verify a specific line belongs to a specific author

**Step 1 — Get the on-chain record for the commit:**
```bash
curl http://127.0.0.1:8000/verify/<commit-sha>
# Note the author and diff_hash in the response
```

**Step 2 — Produce the original diff from any git clone that still has it:**
```bash
git show -p <commit-sha> > my_diff.txt
```

**Step 3 — Verify the hash matches what is on-chain:**
```bash
sha256sum my_diff.txt
# This must equal the diff_hash stored in the transaction
```

**Step 4 — Inspect which lines the author added:**
```bash
grep "^+" my_diff.txt   # lines added by the author
grep "^-" my_diff.txt   # lines the author removed
```

If the hashes match, the diff is authentic. The chain proves it was signed by the CI bot at push time — with the author's GitHub username (`GITHUB_ACTOR`) inside the same signed payload. This means even if someone force-pushes the branch and erases the commit from GitHub history, you still hold cryptographic proof of exactly what was written and by whom.


## File Structure Overview

```
GitChain/
├── gitchain/
│   ├── core/           # Blockchain, blocks, transactions, mining, mempool
│   ├── identity/       # Ed25519 key generation and signing
│   ├── network/        # P2P node, mDNS discovery, message sync
│   ├── api/            # FastAPI REST server and routes
│   ├── cli/            # Click command-line interface
│   ├── dashboard/      # Plain HTML/JS web dashboard
│   └── github-action/  # Node.js GitHub Action script
├── tests/              # pytest test suite (51 tests)
├── .github/workflows/  # GitHub Action workflow
├── gitchain-registry.json  # Developer public key directory
├── pyproject.toml      # Python package config
└── pytest.ini          # asyncio_mode = auto
```

---

## Troubleshooting

**Transaction rejected — invalid signature:**
- Ensure `GITCHAIN_PRIVATE_KEY` secret contains the exact hex content of your `.private.key` file
- The public key in `gitchain-registry.json` must match the private key used for signing

**Transaction rejected — payload hash mismatch (400 error):**
- The node recomputes the payload hash from 8 fields (`author`, `branch`, `commit_hash`, `diff_hash`, `diff_summary`, `owner_pubkey`, `repo`, `timestamp`) and checks it matches the submitted `payload_hash`
- Most common cause: timestamp serialization mismatch — Python must cast to `int` (`"timestamp": int(self.timestamp)`) to match JavaScript's `Math.floor()` output; do not revert this cast
- Also check that all 8 fields match exactly between what the Action sends and what the node recomputes

DISCLAIMER: There is a small difference between a node that you as admin will install, if you have understood it clearly then the first/main node is required to be active in order for the whole thing to run, but if you wish for the GITHUB CI to push it directly to the second system as well which would solve the problem then you can run ngrok in the second system and copy the server link and add a GITHUB secret with the name GITCHAIN_NODE_URL_1 and also add another line (do not delete only add it below the normal one) to .github/workflows/gitchain.yml file which is uploaded to the github repository using gitchain, which is as follows,

- name: Log commit to GitChain 2
        run: node gitchain-submit.js
        working-directory: gitchain/github-action
        env:
          GITCHAIN_PRIVATE_KEY: ${{ secrets.GITCHAIN_PRIVATE_KEY }}
          GITCHAIN_NODE_URL:    ${{ secrets.GITCHAIN_NODE_URL_1 }}
          GITHUB_SHA:           ${{ github.sha }}
          GITHUB_ACTOR:         ${{ github.actor }}
          GITHUB_REPOSITORY:    ${{ github.repository }}
          GITHUB_REF_NAME:      ${{ github.ref_name }}

This will sign using the same key but also send a direct transaction to the second system via ngrok.


Scrapped ideas:
(WARNING: DOES NOT WORK)

### Automatic Discovery (Same LAN)
Just start the node on each machine — they find each other via mDNS within a few seconds:

**Machine A:**
```bash
gitchain node start --data chain-a.json
```

**Machine B:**
```bash
gitchain node start --data chain-b.json
```
