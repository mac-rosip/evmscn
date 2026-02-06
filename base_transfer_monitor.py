#!/usr/bin/env python3
"""
Base Token Transfer Monitor
Subscribes to Transfer events for top tokens on Base and forwards
high-value transfers (>$500) to a webhook.
"""

import asyncio
import json
import aiohttp
import websockets
from decimal import Decimal
from typing import Dict, Optional

# WebSocket endpoint
WSS_URL = "wss://api-base-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400"

# Webhook endpoints
WEBHOOK_URLS = [
    "http://64.247.196.44:3000/webhook",
    "https://webhook.site/d2fb592f-72ac-458b-872c-acfa3c76b607",
]

# Minimum USD value to trigger webhook
MIN_USD_VALUE = 500

# Transfer event topic (keccak256 of "Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Top tokens on Base with their details
# Format: address -> {symbol, decimals, price_usd}
TOP_TOKENS: Dict[str, Dict] = {
    # WETH
    "0x4200000000000000000000000000000000000006": {
        "symbol": "WETH",
        "decimals": 18,
        "price_usd": 2500.0  # Will be updated dynamically
    },
    # USDC (native)
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {
        "symbol": "USDC",
        "decimals": 6,
        "price_usd": 1.0
    },
    # USDbC (bridged USDC)
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": {
        "symbol": "USDbC",
        "decimals": 6,
        "price_usd": 1.0
    },
    # DAI
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {
        "symbol": "DAI",
        "decimals": 18,
        "price_usd": 1.0
    },
    # cbETH (Coinbase Wrapped Staked ETH)
    "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": {
        "symbol": "cbETH",
        "decimals": 18,
        "price_usd": 2650.0  # Will be updated dynamically
    },
    # AERO (Aerodrome)
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": {
        "symbol": "AERO",
        "decimals": 18,
        "price_usd": 1.50  # Will be updated dynamically
    },
    # BRETT
    "0x532f27101965dd16442e59d40670faf5ebb142e4": {
        "symbol": "BRETT",
        "decimals": 18,
        "price_usd": 0.15  # Will be updated dynamically
    },
    # DEGEN
    "0x4ed4e862860bed51a9570b96d89af5e1b0efefed": {
        "symbol": "DEGEN",
        "decimals": 18,
        "price_usd": 0.01  # Will be updated dynamically
    },
    # TOSHI
    "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": {
        "symbol": "TOSHI",
        "decimals": 18,
        "price_usd": 0.0003  # Will be updated dynamically
    },
    # WELL (Moonwell)
    "0xa88594d404727625a9437c3f886c7643872296ae": {
        "symbol": "WELL",
        "decimals": 18,
        "price_usd": 0.05  # Will be updated dynamically
    },
}

# CoinGecko IDs for price fetching
COINGECKO_IDS = {
    "WETH": "weth",
    "cbETH": "coinbase-wrapped-staked-eth",
    "AERO": "aerodrome-finance",
    "BRETT": "brett",
    "DEGEN": "degen-base",
    "TOSHI": "toshi",
    "WELL": "moonwell",
}


async def fetch_prices():
    """Fetch current prices from CoinGecko API."""
    ids = ",".join(COINGECKO_IDS.values())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()

                    # Update prices in TOP_TOKENS
                    for address, token_info in TOP_TOKENS.items():
                        symbol = token_info["symbol"]
                        if symbol in COINGECKO_IDS:
                            cg_id = COINGECKO_IDS[symbol]
                            if cg_id in data and "usd" in data[cg_id]:
                                token_info["price_usd"] = data[cg_id]["usd"]
                                print(f"Updated {symbol} price: ${token_info['price_usd']}")
                else:
                    print(f"Failed to fetch prices: HTTP {response.status}")
    except Exception as e:
        print(f"Error fetching prices: {e}")
        print("Using default/cached prices")


def decode_transfer_log(log: dict) -> Optional[dict]:
    """Decode a Transfer event log."""
    try:
        topics = log.get("topics", [])
        if len(topics) < 3:
            return None

        # topics[0] = Transfer signature
        # topics[1] = from address (padded)
        # topics[2] = to address (padded)
        sender = "0x" + topics[1][-40:]
        recipient = "0x" + topics[2][-40:]

        # data = amount (uint256)
        data = log.get("data", "0x0")
        amount_raw = int(data, 16) if data != "0x" else 0

        contract = log.get("address", "").lower()

        return {
            "sender": sender.lower(),
            "recipient": recipient.lower(),
            "contract": contract,
            "amount_raw": amount_raw,
            "tx_hash": log.get("transactionHash"),
            "block_number": log.get("blockNumber"),
        }
    except Exception as e:
        print(f"Error decoding log: {e}")
        return None


def calculate_usd_value(contract: str, amount_raw: int) -> Optional[float]:
    """Calculate USD value of a transfer."""
    contract_lower = contract.lower()

    if contract_lower not in TOP_TOKENS:
        return None

    token_info = TOP_TOKENS[contract_lower]
    decimals = token_info["decimals"]
    price = token_info["price_usd"]

    amount = Decimal(amount_raw) / Decimal(10 ** decimals)
    usd_value = float(amount) * price

    return usd_value


async def send_to_webhook(session: aiohttp.ClientSession, transfer: dict, usd_value: float, symbol: str):
    """Send transfer data to all webhook endpoints."""
    payload = {
        "r": transfer["recipient"],
        "s": transfer["sender"],
        "contract": transfer["contract"],
        "chain_id": 8453,
        "wss": WSS_URL,
        "rpc_url": "https://api-base-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
    }

    for url in WEBHOOK_URLS:
        try:
            async with session.post(url, json=payload, timeout=5) as response:
                status = response.status
                short_url = url.split("/")[-1][:12] if "webhook.site" in url else "local"
                print(f"[{short_url}] {symbol} ${usd_value:,.2f} | {transfer['sender'][:10]}... -> {transfer['recipient'][:10]}... | HTTP {status}")
        except Exception as e:
            short_url = url.split("/")[-1][:12] if "webhook.site" in url else "local"
            print(f"[{short_url}] ERROR: {e}")


async def update_prices_periodically():
    """Update prices every 5 minutes."""
    while True:
        await fetch_prices()
        await asyncio.sleep(300)  # 5 minutes


async def monitor_transfers():
    """Main monitoring loop."""
    # Initial price fetch
    await fetch_prices()

    # Start price updater in background
    asyncio.create_task(update_prices_periodically())

    # Create HTTP session for webhooks
    async with aiohttp.ClientSession() as http_session:
        while True:
            try:
                print(f"Connecting to {WSS_URL}...")
                async with websockets.connect(WSS_URL, ping_interval=30, ping_timeout=10) as ws:
                    print("Connected! Subscribing to Transfer events...")

                    # Subscribe to logs for all top tokens
                    subscribe_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_subscribe",
                        "params": [
                            "logs",
                            {
                                "address": list(TOP_TOKENS.keys()),
                                "topics": [TRANSFER_TOPIC]
                            }
                        ]
                    }

                    await ws.send(json.dumps(subscribe_request))

                    # Wait for subscription confirmation
                    response = await ws.recv()
                    result = json.loads(response)

                    if "result" in result:
                        print(f"Subscribed! Subscription ID: {result['result']}")
                        print(f"Monitoring {len(TOP_TOKENS)} tokens for transfers > ${MIN_USD_VALUE}")
                        print("-" * 60)
                    else:
                        print(f"Subscription failed: {result}")
                        continue

                    # Process incoming logs
                    async for message in ws:
                        try:
                            data = json.loads(message)

                            if "params" not in data:
                                continue

                            log = data["params"]["result"]
                            transfer = decode_transfer_log(log)

                            if not transfer:
                                continue

                            usd_value = calculate_usd_value(transfer["contract"], transfer["amount_raw"])

                            if usd_value is None:
                                continue

                            token_info = TOP_TOKENS.get(transfer["contract"].lower(), {})
                            symbol = token_info.get("symbol", "???")

                            # Only process transfers > $500
                            if usd_value >= MIN_USD_VALUE:
                                print(f"[TRANSFER] {symbol}: ${usd_value:,.2f} | TX: {transfer['tx_hash']}")
                                await send_to_webhook(http_session, transfer, usd_value, symbol)

                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            print(f"Error processing message: {e}")
                            continue

            except websockets.exceptions.ConnectionClosed as e:
                print(f"Connection closed: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Error: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    print("=" * 60)
    print("Base Token Transfer Monitor")
    print(f"Webhooks: {len(WEBHOOK_URLS)}")
    print(f"Min Value: ${MIN_USD_VALUE}")
    print("=" * 60)

    try:
        asyncio.run(monitor_transfers())
    except KeyboardInterrupt:
        print("\nShutting down...")
