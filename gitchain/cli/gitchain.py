
import asyncio
import json
import os
import sys
import threading
from pathlib import Path

import click

from gitchain.identity.keygen import save_keypair, register_public_key
from gitchain.identity.signer import pubkey_from_private


@click.group()
def cli():
    """GitChain — Decentralized Contribution Verifier"""
    pass



@cli.command()
@click.option("--name",   required=True, help="Developer name (e.g. 'Alice')")
@click.option("--email",  required=True, help="Developer email (e.g. alice@company.com)")
@click.option("--output", default=".", show_default=True, help="Directory for key files")
@click.option("--registry", default="gitchain-registry.json", show_default=True,
              help="Path to gitchain-registry.json to update")
def keygen(name, email, output, registry):
    """
    Generate an Ed25519 keypair for a developer.

    Outputs:
      <email>.private.key  — keep secret, add to GitHub Secrets as GITCHAIN_PRIVATE_KEY
      <email>.public.key   — safe to share, added to gitchain-registry.json

    Run this once per developer. The private key never leaves your machine.
    """
    private_hex, public_hex = save_keypair(name=name, email=email, output_dir=output)
    register_public_key(name=name, email=email, public_hex=public_hex, registry_path=registry)

    click.echo(f"\n✓ Keypair generated for {name} <{email}>")
    click.echo(f"\n  Private key → {Path(output) / f'{email}.private.key'}")
    click.echo( "    Add this file's contents to GitHub Secrets as GITCHAIN_PRIVATE_KEY")
    click.echo(f"\n  Public key  → {Path(output) / f'{email}.public.key'}")
    click.echo(f"    Added to {registry} — commit this file to your repository")
    click.echo(f"\n  Public key hex: {public_hex}")



@cli.command()
@click.argument("commit_sha")
@click.option("--node", "node_url", default="http://127.0.0.1:8000", show_default=True,
              help="GitChain node API URL")
def verify(commit_sha, node_url):
    
    import urllib.request
    import urllib.error

    url = f"{node_url.rstrip('/')}/verify/{commit_sha}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        click.echo(f"Error: cannot reach node at {node_url} — {e.reason}", err=True)
        sys.exit(2)

    if data.get("on_chain"):
        tx   = data.get("transaction", {})
        bidx = data.get("block_index", "?")
        click.echo(f"\n  COMMIT VERIFIED ON-CHAIN")
        click.echo(f"  commit  : {commit_sha}")
        click.echo(f"  block   : #{bidx}")
        click.echo(f"  repo    : {tx.get('repo', '?')}")
        click.echo(f"  branch  : {tx.get('branch', '?')}")
        click.echo(f"  author  : {tx.get('author', '?')}")
        click.echo(f"  time    : {tx.get('timestamp', '?')}")
        sys.exit(0)
    else:
        click.echo(f"\n  NOT FOUND ON-CHAIN: {commit_sha}")
        click.echo(f"  {data.get('message', '')}")
        sys.exit(1)




@cli.command()
@click.option("--node", "node_url", default="http://127.0.0.1:8000", show_default=True,
              help="GitChain node API URL")
def status(node_url):
    """Show local node status: chain height, connected peers, mempool size."""
    import urllib.request
    import urllib.error

    url = f"{node_url.rstrip('/')}/status"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        click.echo(f"Error: cannot reach node at {node_url} — {e.reason}", err=True)
        sys.exit(2)

    click.echo(f"\n  Node ID      : {data.get('node_id')}")
    click.echo(f"  Chain height : {data.get('chain_height')} blocks")
    click.echo(f"  Mempool      : {data.get('mempool_size')} pending txs")
    click.echo(f"  Peers        : {data.get('peer_count')} connected")
    for p in data.get("peers", []):
        click.echo(f"    - {p}")



@cli.group()
def node():
    """Manage the GitChain node daemon."""
    pass


@node.command("start")
@click.option("--port",       default=6331,            show_default=True, help="P2P TCP port")
@click.option("--api-port",   default=8000,            show_default=True, help="REST API port")
@click.option("--difficulty", default=3,               show_default=True, help="PoW difficulty (leading zeros)")
@click.option("--data",       default="chain.json",    show_default=True, help="Chain persistence file")
@click.option("--no-mdns",    is_flag=True, default=False,                help="Disable mDNS peer discovery")
@click.option("--peer",       multiple=True,                               help="Connect to peer host:port on startup")
def node_start(port, api_port, difficulty, data, no_mdns, peer):
    
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )

    from gitchain.network.node import GitChainNode
    from gitchain.api.server import create_app
    import uvicorn

    click.echo(f"\nStarting GitChain node")
    click.echo(f"  P2P port  : {port}")
    click.echo(f"  API port  : {api_port}")
    click.echo(f"  Difficulty: {difficulty} leading zeros")
    click.echo(f"  Chain file: {data}")
    click.echo(f"  mDNS      : {'disabled' if no_mdns else 'enabled'}\n")

    async def run_node():
        gitchain_node = GitChainNode(
            port=port,
            difficulty=difficulty,
            data_path=data,
            enable_mdns=not no_mdns,
        )
        await gitchain_node.start()

        # Connect to any manually specified peers
        for peer_addr in peer:
            if peer_addr.startswith("http"):
                raise click.UsageError(
                    f"--peer takes host:port (TCP), not a URL.\n"
                    f"  Got:      {peer_addr}\n"
                    f"  Example:  --peer 192.168.1.10:6331\n"
                    f"  Note: ngrok HTTP URLs work for GITCHAIN_NODE_URL (GitHub Action) "
                    f"but not for --peer (raw TCP P2P)."
                )
            try:
                host, p = peer_addr.rsplit(":", 1)
                await gitchain_node.connect_to_peer(host, int(p))
                click.echo(f"  Connected to peer {peer_addr}")
            except ValueError:
                raise click.UsageError(
                    f"--peer must be host:port, e.g. 192.168.1.10:6331 (got: {peer_addr})"
                )

        # Run REST API in a background thread (uvicorn is blocking)
        app = create_app(gitchain_node)

        def run_api():
            uvicorn.run(app, host="0.0.0.0", port=api_port, log_level="warning")

        api_thread = threading.Thread(target=run_api, daemon=True)
        api_thread.start()

        click.echo(f"  Dashboard : http://127.0.0.1:{api_port}/dashboard")
        click.echo(f"  API docs  : http://127.0.0.1:{api_port}/docs")
        click.echo("\nNode running. Press Ctrl+C to stop.\n")

        try:
            # Run until interrupted
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            click.echo("\nShutting down...")
            await gitchain_node.stop()

    try:
        asyncio.run(run_node())
    except KeyboardInterrupt:
        pass



def main():
    cli()


if __name__ == "__main__":
    main()
