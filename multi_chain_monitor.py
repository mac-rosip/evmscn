#!/usr/bin/env python3
"""
Multi-Chain Token Transfer Monitor
Monitors top tokens across all EVM-compatible chains and forwards
high-value transfers (>$500) to a webhook.
"""

import asyncio
import json
import aiohttp
import websockets
from decimal import Decimal
from typing import Dict, Optional, List
from dataclasses import dataclass

# Webhook endpoints
WEBHOOK_URLS = [
    "http://64.247.196.44:3000/webhook",
    "https://webhook.site/d2fb592f-72ac-458b-872c-acfa3c76b607",
]

# Minimum USD value to trigger webhook
MIN_USD_VALUE = 100000

# Transfer event topic (keccak256 of "Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass
class ChainConfig:
    name: str
    chain_id: int
    rpc_url: str
    tokens: Dict[str, Dict]  # address -> {symbol, decimals, price_usd}
    wss: Optional[str] = None
    poll_interval: float = 2.0  # seconds between HTTP polls (only used when wss is None)


# EVM chains configuration with top tokens
CHAINS: List[ChainConfig] = [
    # Ethereum Mainnet (alt: api-ethereum-mainnet-reth for Reth client)
    ChainConfig(
        name="Ethereum",
        chain_id=1,
        wss="wss://api-ethereum-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-ethereum-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xdac17f958d2ee523a2206206994597c13d831ec7": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x6b175474e89094c44da98b954eedeac495271d0f": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": {"symbol": "AAVE", "decimals": 18, "price_usd": 250.0},
            "0x514910771af9ca656af840dff83e8264ecf986ca": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": {"symbol": "stETH", "decimals": 18, "price_usd": 2500.0},
            "0xbe9895146f7af43049ca1c1ae358b0541ea49704": {"symbol": "cbETH", "decimals": 18, "price_usd": 2650.0},
            "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x5a98fcbea516cf06857215779fd812ca3bef1b32": {"symbol": "LDO", "decimals": 18, "price_usd": 2.0},
            "0xd533a949740bb3306d119cc777fa900ba034cd52": {"symbol": "CRV", "decimals": 18, "price_usd": 0.5},
            "0x4d224452801aced8b2f0aebe155379bb5d594381": {"symbol": "APE", "decimals": 18, "price_usd": 1.5},
            "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": {"symbol": "SHIB", "decimals": 18, "price_usd": 0.00001},
            "0x6982508145454ce325ddbe47a25d4ec3d2311933": {"symbol": "PEPE", "decimals": 18, "price_usd": 0.00001},
            "0x111111111117dc0aa78b770fa6a738034120c302": {"symbol": "1INCH", "decimals": 18, "price_usd": 0.4},
            "0xc944e90c64b2c07662a292be6244bdf05cda44a7": {"symbol": "GRT", "decimals": 18, "price_usd": 0.2},
            "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": {"symbol": "MKR", "decimals": 18, "price_usd": 1500.0},
            "0x853d955acef822db058eb8505911ed77f175b99e": {"symbol": "FRAX", "decimals": 18, "price_usd": 1.0},
            "0xa693b19d2931d498c5b318df961919bb4aee87a5": {"symbol": "UST", "decimals": 6, "price_usd": 1.0},
            "0x4fabb145d64652a948d72533023f6e7a623c7c53": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
            "0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e": {"symbol": "YFI", "decimals": 18, "price_usd": 8000.0},
            "0xc00e94cb662c3520282e6f5717214004a7f26888": {"symbol": "COMP", "decimals": 18, "price_usd": 50.0},
            "0xba100000625a3754423978a60c9317c58a424e3d": {"symbol": "BAL", "decimals": 18, "price_usd": 3.0},
        }
    ),
    # Arbitrum (alt: api-arbitrum-mainnet-full for Full Node)
    ChainConfig(
        name="Arbitrum",
        chain_id=42161,
        wss="wss://api-arbitrum-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-arbitrum-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xaf88d065e77c8cc2239327c5edb3a432268e5831": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x912ce59144191c1204e64559fe8253a0e49e6548": {"symbol": "ARB", "decimals": 18, "price_usd": 0.8},
            "0xfc5a1a6eb076a2c7ad06ed22c90d7e710e35ad0a": {"symbol": "GMX", "decimals": 18, "price_usd": 25.0},
            "0xf97f4df75117a78c1a5a0dbb814af92458539fb4": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x5979d7b546e38e414f7e9822514be443a4800529": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0xfa7f8980b0f1e64a2062791cc3b0871572f1f7f0": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0x6c84a8f1c29108f47a79964b5fe888d4f4d0de40": {"symbol": "tBTC", "decimals": 18, "price_usd": 95000.0},
            "0x3082cc23568ea640225c2467653db90e9250aaa0": {"symbol": "RDNT", "decimals": 18, "price_usd": 0.05},
            "0x17fc002b466eec40dae837fc4be5c67993ddbd6f": {"symbol": "FRAX", "decimals": 18, "price_usd": 1.0},
            "0x539bde0d7dbd336b79148aa742883198bbf60342": {"symbol": "MAGIC", "decimals": 18, "price_usd": 0.5},
            "0x354a6da3fcde098f8389cad84b0182725c6c91de": {"symbol": "COMP", "decimals": 18, "price_usd": 50.0},
            "0x11cdb42b0eb46d95f990bedd4695a6e3fa034978": {"symbol": "CRV", "decimals": 18, "price_usd": 0.5},
            "0xd4d42f0b6def4ce0383636770ef773390d85c61a": {"symbol": "SUSHI", "decimals": 18, "price_usd": 1.0},
            "0x6694340fc020c5e6b96567843da2df01b2ce1eb6": {"symbol": "STG", "decimals": 18, "price_usd": 0.4},
            "0x0c880f6761f1af8d9aa9c466984b80dab9a8c9e8": {"symbol": "PENDLE", "decimals": 18, "price_usd": 5.0},
        }
    ),
    # Base
    ChainConfig(
        name="Base",
        chain_id=8453,
        wss="wss://api-base-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-base-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": {"symbol": "USDbC", "decimals": 6, "price_usd": 1.0},
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": {"symbol": "cbETH", "decimals": 18, "price_usd": 2650.0},
            "0x940181a94a35a4569e4529a3cdfb74e38fd98631": {"symbol": "AERO", "decimals": 18, "price_usd": 1.50},
            "0x532f27101965dd16442e59d40670faf5ebb142e4": {"symbol": "BRETT", "decimals": 18, "price_usd": 0.10},
            "0x4ed4e862860bed51a9570b96d89af5e1b0efefed": {"symbol": "DEGEN", "decimals": 18, "price_usd": 0.007},
            "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": {"symbol": "TOSHI", "decimals": 18, "price_usd": 0.0002},
            "0xa88594d404727625a9437c3f886c7643872296ae": {"symbol": "WELL", "decimals": 18, "price_usd": 0.05},
            "0xc5fecc3a29fb57b5024eec8a2239d4621e111cbe": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x236aa50979d5f3de3bd1eeb40e81137f22ab794b": {"symbol": "tBTC", "decimals": 18, "price_usd": 95000.0},
            "0x0555e30da8f98308edb960aa94c0db47230d2b9c": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x22e6966b799c4d5b13be962e1d117b56327fda66": {"symbol": "SNX", "decimals": 18, "price_usd": 2.5},
            "0x4158734d47fc9692176b5085e0f52ee0da5d47f1": {"symbol": "BAL", "decimals": 18, "price_usd": 3.0},
            "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x368181499736d0c0cc614dbb145e2ec1ac86b8c6": {"symbol": "LUSD", "decimals": 18, "price_usd": 1.0},
            "0xb6fe221fe9eef5aba221c348ba20a1bf5e73624c": {"symbol": "rETH", "decimals": 18, "price_usd": 2700.0},
            "0x9e1028f5f1d5ede59748ffcee5532509976840e0": {"symbol": "COMP", "decimals": 18, "price_usd": 50.0},
            "0x417ac0e078398c154edfadd9ef675d30be60af93": {"symbol": "crvUSD", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Optimism
    ChainConfig(
        name="Optimism",
        chain_id=10,
        wss="wss://api-optimism-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-optimism-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x0b2c639c533813f4aa9d7837caf62653d097ff85": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x7f5c764cbc14f9669b88837ca1490cca17c31607": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x68f180fcce6836688e9084f035309e29bf0a2095": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x4200000000000000000000000000000000000042": {"symbol": "OP", "decimals": 18, "price_usd": 2.0},
            "0x1f32b1c2345538c0c6f582fcb022739c4a194ebb": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x350a791bfc2c21f9ed5d10980dad2e2638ffa7f6": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x8700daec35af8ff88c16bdf0418774cb3d7599b4": {"symbol": "SNX", "decimals": 18, "price_usd": 2.5},
        }
    ),
    # Polygon
    ChainConfig(
        name="Polygon",
        chain_id=137,
        wss="wss://api-polygon-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-polygon-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": {"symbol": "WMATIC", "decimals": 18, "price_usd": 0.5},
            "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x53e0bca35ec356bd5dddfebbd1fc0fd03fabad39": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0xb33eaad8d922b1083446dc23f610c2567fb5180f": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0xd6df932a45c0f255f85145f286ea0b292b21c90b": {"symbol": "AAVE", "decimals": 18, "price_usd": 250.0},
        }
    ),
    # BSC
    ChainConfig(
        name="BSC",
        chain_id=56,
        wss="wss://api-bsc-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-bsc-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": {"symbol": "WBNB", "decimals": 18, "price_usd": 600.0},
            "0x55d398326f99059ff775485246999027b3197955": {"symbol": "USDT", "decimals": 18, "price_usd": 1.0},
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": {"symbol": "USDC", "decimals": 18, "price_usd": 1.0},
            "0xe9e7cea3dedca5984780bafc599bd69add087d56": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
            "0x2170ed0880ac9a755fd29b2688956bd959f933f8": {"symbol": "ETH", "decimals": 18, "price_usd": 2500.0},
            "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": {"symbol": "BTCB", "decimals": 18, "price_usd": 95000.0},
            "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82": {"symbol": "CAKE", "decimals": 18, "price_usd": 2.5},
            "0xf8a0bf9cf54bb92f17374d9e9a321e6a111a51bd": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x1d2f0da169ceb9fc7b3144628db156f3f6c60dbe": {"symbol": "XRP", "decimals": 18, "price_usd": 2.5},
            "0x3ee2200efb3400fabb9aacf31297cbdd1d435d47": {"symbol": "ADA", "decimals": 18, "price_usd": 0.7},
            "0x7083609fce4d1d8dc0c979aab8c869ea2c873402": {"symbol": "DOT", "decimals": 18, "price_usd": 5.0},
            "0xba2ae424d960c26247dd6c32edc70b295c744c43": {"symbol": "DOGE", "decimals": 8, "price_usd": 0.1},
            "0x4338665cbb7b2485a8855a139b75d5e34ab0db94": {"symbol": "LTC", "decimals": 18, "price_usd": 100.0},
            "0x8ff795a6f4d97e7887c79bea79aba5cc76444adf": {"symbol": "BCH", "decimals": 18, "price_usd": 400.0},
            "0xcc42724c6683b7e57334c4e856f4c9965ed682bd": {"symbol": "MATIC", "decimals": 18, "price_usd": 0.5},
            "0xbf5140a22578168fd562dccf235e5d43a02ce9b1": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0x14016e85a25aeb13065688cafb43044c2ef86784": {"symbol": "TUSD", "decimals": 18, "price_usd": 1.0},
            "0xc748673057861a797275cd8a068abb95a902e8de": {"symbol": "BABY", "decimals": 18, "price_usd": 0.001},
            "0x8595f9da7b868b1822194faed312235e43007b49": {"symbol": "BTT", "decimals": 18, "price_usd": 0.000001},
            "0x031b41e504677879370e9dbcf937283a8691fa7f": {"symbol": "FDUSD", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Gnosis
    ChainConfig(
        name="Gnosis",
        chain_id=100,
        wss="wss://api-gnosis-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-gnosis-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d": {"symbol": "WXDAI", "decimals": 18, "price_usd": 1.0},
            "0x6a023ccd1ff6f2045c3309768ead9e68f978f6e1": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xddafbb505ad214d7b80b1f830fccc89b60fb7a83": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x4ecaba5870353805a9f068101a40e0f32ed605c6": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x8e5bbbb09ed1ebde8674cda39a0c169401db4252": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x9c58bacc331c9aa871afd802db6379a98e80cedb": {"symbol": "GNO", "decimals": 18, "price_usd": 200.0},
            "0x6c76971f98945ae98dd7d4dfca8711ebea946ea6": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0xe2e73a1c69ecf83f464efce6a5be353a37ca09b2": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x4d18815d14fe5c3304e87b3fa18318baa5c23820": {"symbol": "SAFE", "decimals": 18, "price_usd": 0.8},
            "0x44fa8e6f47987339850636f88629646662444217": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Linea
    ChainConfig(
        name="Linea",
        chain_id=59144,
        wss="wss://api-linea-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-linea-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xe5d7c2a44ffddf6b295a15c148167daaaf5cf34f": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x176211869ca2b568f2a7d4ee941e073a821ee1ff": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xa219439258ca9da29e9cc4ce5596924745e12b93": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x4af15ec2a0bd43db75dd04e62faa3b8ef36b00d5": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x3aab2285ddcddad8edf438c1bab47e1a9d05a9b4": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0xb5bedd42000b71fdde22d3ee8a79bd49a568fc8f": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x5471ea8f739dd37e9b81be9c5c77754d8aa953e4": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
            "0x636b22bc471c955a8db60f28d4795066a8201fa3": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0x265b25e22bcd7f10a5bd6e6410f10537cc7567e8": {"symbol": "MATIC", "decimals": 18, "price_usd": 0.5},
            "0x7d43aabc515c356145049227cee54b608342c0ad": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Scroll
    ChainConfig(
        name="Scroll",
        chain_id=534352,
        wss="wss://api-scroll-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-scroll-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x5300000000000000000000000000000000000004": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x06efdbff2a14a7c8e15944d1f4a48f9f95f663a4": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xf55bec9cafdbe8730f096aa55dad6d22d44099df": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xca77eb3fefe3725dc33bccb54edefc3d9f764f97": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x3c1bca5a656e69edcd0d4e36bebb3fcdaca60cf1": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0xf610a9dfb7c89644979b4a0f27063e9e7d7cda32": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0xd29687c813d741e2f938f4ac377128810e217b1b": {"symbol": "SCR", "decimals": 18, "price_usd": 0.5},
            "0x79379c0e09a41d7978f883a56246290ee9a8c4d3": {"symbol": "AAVE", "decimals": 18, "price_usd": 250.0},
            "0x3ba89d490ab1c0c9cc2313385b30710f8fd4f9d4": {"symbol": "STONE", "decimals": 18, "price_usd": 2500.0},
            "0xaa111c62cdeef205f70e6722d1e22274274ec12f": {"symbol": "LUSD", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # zkSync Era
    ChainConfig(
        name="zkSync",
        chain_id=324,
        wss="wss://api-zksync-era-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-zksync-era-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x5aea5775959fbc2557cc8789bc1bf90a239d9a91": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x1d17cbcf0d6d143135ae902365d2e5e2a16538d4": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x493257fd37edb34451f62edf8d2a0c418852ba4c": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x4b9eb6c0b6ea15176bbf62841c6b2a8a398cb656": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0xbbeb516fb02a01611cbbe0453fe3c580d7281011": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x703b52f2b28febcb60e1372858af5b18849fe867": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e": {"symbol": "ZK", "decimals": 18, "price_usd": 0.15},
            "0x32fd44bb869620c0ef993754c8a00be67c464806": {"symbol": "RDNT", "decimals": 18, "price_usd": 0.05},
            "0x3355df6d4c9c3035724fd0e3914de96a5a83aaf4": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0x0e97c7a0f8b2c9885c8ac9fc6136e829cbc21d42": {"symbol": "MUTE", "decimals": 18, "price_usd": 0.05},
        }
    ),
    # Blast
    ChainConfig(
        name="Blast",
        chain_id=81457,
        wss="wss://api-blast-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-blast-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4300000000000000000000000000000000000004": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x4300000000000000000000000000000000000003": {"symbol": "USDB", "decimals": 18, "price_usd": 1.0},
            "0xb1a5700fa2358173fe465e6ea4ff52e36e88e2ad": {"symbol": "BLAST", "decimals": 18, "price_usd": 0.01},
            "0x2416092f143378750bb29b79ed961ab195cceea5": {"symbol": "ezETH", "decimals": 18, "price_usd": 2550.0},
            "0x73c369f61c90f03eb0dd172e95c90208a28dc5bc": {"symbol": "JUICE", "decimals": 18, "price_usd": 0.001},
            "0xf7bc58b8d8f97adc129cfc4c9f45ce3c0e1d2692": {"symbol": "wrsETH", "decimals": 18, "price_usd": 2600.0},
            "0x9e0d7d79735e1c63333128149c7b616a0dc0bbdb": {"symbol": "PUMP", "decimals": 18, "price_usd": 0.0001},
            "0x818a92bc81aad0053d72ba753fb5bc3d0c5c0923": {"symbol": "PAC", "decimals": 18, "price_usd": 0.01},
            "0x76da31d7c9cbeae102aff34d3398bc450c8374c1": {"symbol": "MIM", "decimals": 18, "price_usd": 1.0},
            "0x15d24de366f69b835be19f7cf9447e770315dd80": {"symbol": "KAP", "decimals": 18, "price_usd": 0.0001},
        }
    ),
    # Moonbeam
    ChainConfig(
        name="Moonbeam",
        chain_id=1284,
        wss="wss://api-moonbeam.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-moonbeam.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xacc15dc74880c9944775448304b263d191c6077f": {"symbol": "WGLMR", "decimals": 18, "price_usd": 0.25},
            "0xfa9343c3897324496a05fc75abed6bac29f8a40f": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x931715fee2d06333043d11f658c8ce934ac61d0c": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xefaeee334f0fd1712f9a8cc375f427d9cdd40d73": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x765277eebeca2e31912c9946eae1021199b39c61": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x922d641a426dcffaef11680e5358f34d97d112e1": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0xffffffff1fcacbd218edc0eba20fc2308c778080": {"symbol": "xcDOT", "decimals": 10, "price_usd": 5.0},
            "0xfffffffffffffffffffffffffffffffffffffed5": {"symbol": "WELL", "decimals": 18, "price_usd": 0.05},
            "0x30d2a9f5fdf90ace8c17952cbb4ee48a55d916a7": {"symbol": "STELLA", "decimals": 18, "price_usd": 0.02},
            "0xcd3b51d98478d53f4515a306be565c6eebef1d58": {"symbol": "GLINT", "decimals": 18, "price_usd": 0.001},
        }
    ),
    # Celo
    ChainConfig(
        name="Celo",
        chain_id=42220,
        wss="wss://api-celo-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-celo-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x471ece3750da237f93b8e339c536989b8978a438": {"symbol": "CELO", "decimals": 18, "price_usd": 0.6},
            "0x765de816845861e75a25fca122bb6898b8b1282a": {"symbol": "cUSD", "decimals": 18, "price_usd": 1.0},
            "0xd8763cba276a3738e6de85b4b3bf5fded6d6ca73": {"symbol": "cEUR", "decimals": 18, "price_usd": 1.1},
            "0xef4229c8c3250c675f21bcefa42f58efbff6002a": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x48065fbbe25f71c9282ddf5e1cd6d6a887483d5e": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x90ca507a5d4458a4c6c6249d186b6dcb02a5bccd": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2def4285787d58a2f811af24755a8150622f4361": {"symbol": "cETH", "decimals": 18, "price_usd": 2500.0},
            "0xd629eb00deced2a080b7ec630ef6ac117e614f1b": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x37f750b7cc259a2f741af45294f6a16572cf5cad": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0x73a210637f6f6b7005512677ba6b3c96bb4aa44b": {"symbol": "MOBI", "decimals": 18, "price_usd": 0.01},
        }
    ),
    # Cronos
    ChainConfig(
        name="Cronos",
        chain_id=25,
        wss="wss://api-cronos-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-cronos-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x5c7f8a570d578ed84e63fdfa7b1ee72deae1ae23": {"symbol": "WCRO", "decimals": 18, "price_usd": 0.1},
            "0xe44fd7fcb2b1581822d0c862b68222998a0c299a": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xc21223249ca28397b4b6541dffaecc539bff0c59": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x66e428c3f67a68878562e79a0234c1f83c208770": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xf2001b145b43032aaf5ee2884e456ccd805f677d": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x062e66477faf219f25d27dced647bf57c3107d52": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x87ef305b5292d6e5fdc75e2e5f4c807e01e74c4a": {"symbol": "VVS", "decimals": 18, "price_usd": 0.000003},
            "0x2d03bece6747adc00e1a131bba1469c15fd11e03": {"symbol": "TONIC", "decimals": 18, "price_usd": 0.0000002},
            "0xbed48612bc69fa1cab67052b42a95fb30c1bcfee": {"symbol": "SHIB", "decimals": 18, "price_usd": 0.00001},
            "0xb888d8dd1733d72681b30c00ee76bde93ae7aa93": {"symbol": "ATOM", "decimals": 6, "price_usd": 8.0},
        }
    ),
    # Zora
    ChainConfig(
        name="Zora",
        chain_id=7777777,
        wss="wss://api-zora-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-zora-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xcccccccc7021b32ebb4e8c08314bd62f7c653ec4": {"symbol": "USDzC", "decimals": 6, "price_usd": 1.0},
            "0x9e7e6cc0ca6b22c27a1b2d6a8f578c77b46e74ec": {"symbol": "ENJOY", "decimals": 18, "price_usd": 0.001},
            "0x078540eecc8b6d89949c9c7d5e8e91eab64f6696": {"symbol": "IMAGINE", "decimals": 18, "price_usd": 0.0001},
            "0xaa1e1cf9b5677f0f37e5a662abd1f854e8f7d177": {"symbol": "DEGEN", "decimals": 18, "price_usd": 0.007},
            "0x1111111111166b7fe7bd91427724b487980afc69": {"symbol": "ZORA", "decimals": 18, "price_usd": 0.05},
            "0xcdf04e619fab5f1354e917fbb0f95ac7fd38c0ed": {"symbol": "BRETT", "decimals": 18, "price_usd": 0.10},
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x4200000000000000000000000000000000000042": {"symbol": "OP", "decimals": 18, "price_usd": 2.0},
            "0x220ecbc87e0f19818cb4ad064d3e1e85fcc6ff2b": {"symbol": "WELL", "decimals": 18, "price_usd": 0.05},
        }
    ),
    # Sonic
    ChainConfig(
        name="Sonic",
        chain_id=146,
        wss="wss://api-sonic-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-sonic-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x039e2fb66102314ce7b64ce5ce3e5183bc94ad38": {"symbol": "wS", "decimals": 18, "price_usd": 0.5},
            "0x50c42deacd8fc9773493ed674b675be577f2634b": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x29219dd400f2bf60e5a23d13be72b486d4038894": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0xd3dcae6c2306e9584c38e0f30aadfed9f0399d5a": {"symbol": "scUSD", "decimals": 18, "price_usd": 1.0},
            "0x2d0e0814e62d80056181f5cd932274405966e4f0": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x4253e7fb850dd2925b4bbc478c929b94f47cd64a": {"symbol": "scETH", "decimals": 18, "price_usd": 2500.0},
            "0xe715cbab6f86f11b2826f69b3b3d19c9c95b7b85": {"symbol": "BEETS", "decimals": 18, "price_usd": 0.02},
            "0x2f2a7e61f06ad1c908c8d56e0ecce9e0f72ec861": {"symbol": "stS", "decimals": 18, "price_usd": 0.5},
            "0x1a88f84e9d4df77ab7fe5db64fa7e7fc89c1b597": {"symbol": "SWPx", "decimals": 18, "price_usd": 0.1},
            "0x53a75d08a5bc27bec8b9dd0de4ec01c2e9e12f0d": {"symbol": "GOGLZ", "decimals": 18, "price_usd": 0.001},
        }
    ),
    # Mantle
    ChainConfig(
        name="Mantle",
        chain_id=5000,
        wss="wss://api-mantle-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-mantle-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x78c1b0c915c4faa5fffa6cabf0219da63d7f4cb8": {"symbol": "WMNT", "decimals": 18, "price_usd": 1.0},
            "0xdeaddeaddeaddeaddeaddeaddeaddeaddead1111": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x09bc4e0d864854c6afb6eb9a9cdf58ac190d0df9": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x201eba5cc46d216ce6dc03f6a759e8e766e956ae": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xcabae6f6ea1ecab08ad02fe02ce9a44f09aebfa2": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x5be26527e817998a7206475496fde1e68957c5a6": {"symbol": "mETH", "decimals": 18, "price_usd": 2600.0},
            "0xe6829d9a7ee3040e1276fa75293bde931859e8fa": {"symbol": "cmETH", "decimals": 18, "price_usd": 2600.0},
            "0xcda86a272531e8640cd7f1a92c01839911b90bb0": {"symbol": "mUSD", "decimals": 18, "price_usd": 1.0},
            "0x0b61c4f33bcdef83359ab97673cb5961c6435f4e": {"symbol": "MINU", "decimals": 18, "price_usd": 0.0001},
            "0x6d3b8c76c5396642960243febf736c6be8b60562": {"symbol": "PUFF", "decimals": 18, "price_usd": 0.01},
        }
    ),
    # Berachain
    ChainConfig(
        name="Berachain",
        chain_id=80094,
        wss="wss://api-berachain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-berachain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x6969696969696969696969696969696969696969": {"symbol": "WBERA", "decimals": 18, "price_usd": 5.0},
            "0x0555e30da8f98308edb960aa94c0db47230d2b9c": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xfcbd14dc51f0a4d49d5e53c2e0950e0bc26d0dce": {"symbol": "HONEY", "decimals": 18, "price_usd": 1.0},
            "0x549943e04f40284185054145c6e4e9568c1d3241": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x779877a7b0d9e8603169ddbd7836e478b4624789": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x286f1c3f0323db9c91d1e8f45c8df2d065ab5fae": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x2f6f07cdcf3588944bf4c42ac74ff24bf56e7590": {"symbol": "stBERA", "decimals": 18, "price_usd": 5.0},
            "0x656b95e550c07a9ffe548bd4085c72418ceb1dba": {"symbol": "iBGT", "decimals": 18, "price_usd": 3.0},
            "0xac03caba51e17c86c921e1f6cbfbdc91f8bb2e6b": {"symbol": "yBGT", "decimals": 18, "price_usd": 3.0},
            "0x46efc86f0d7455f135cc9df501673739d513e982": {"symbol": "oBERO", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Pulsechain
    ChainConfig(
        name="Pulsechain",
        chain_id=369,
        wss="wss://api-pulse-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-pulse-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xa1077a294dde1b09bb078844df40758a5d0f9a27": {"symbol": "WPLS", "decimals": 18, "price_usd": 0.00003},
            "0x02dcdd04e3f455d838cd1249292c58f3b79e3c3c": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x15d38573d2feeb82e7ad5187ab8c1d52810b1f07": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x0cb6f5a34ad42ec934882a05265a7d5f59b51a2f": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xefd766ccb38eaf1dfd701853bfce31359239f305": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2b591e99afe9f32eaa6214f7b7629768c40eeb39": {"symbol": "HEX", "decimals": 8, "price_usd": 0.005},
            "0x95b303987a60c71504d99aa1b13b4da07b0790ab": {"symbol": "PLSX", "decimals": 18, "price_usd": 0.00005},
            "0x2fa878ab3f87cc1c9737fc071108f904c0b0c95d": {"symbol": "INC", "decimals": 18, "price_usd": 0.01},
            "0x57fde0a71132198bbec939b98976993d8d89d225": {"symbol": "eHEX", "decimals": 8, "price_usd": 0.005},
            "0xb17d901469b9208b17d916112988a3fed19b5ca1": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Unichain
    ChainConfig(
        name="Unichain",
        chain_id=130,
        wss="wss://api-unichain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-unichain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x078d782b760474a361dda0af3839290b0ef57ad6": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x8f187aa05619a017077f5308904739877ce9ea21": {"symbol": "UNI", "decimals": 18, "price_usd": 8.0},
            "0x588ce4f028d8e7b53b687865d6a67b3a54c75518": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xe9a6107b5bb5a739d5e0c0aa58e9c63cd09adfb3": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0xc27636e2a42a086ca12b17d7108f79429a683bd1": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x35e5db674d8e93a03d814fa0ada70731efe8a4b9": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x2f6f07cdcf3588944bf4c42ac74ff24bf56e7590": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
            "0x094e5a2df377a7ba46692b3d34cf1fc434ad5a18": {"symbol": "AAVE", "decimals": 18, "price_usd": 250.0},
            "0x876fa29d66bbdfc8e9a1f5a6df7b19b26b2c8b29": {"symbol": "OP", "decimals": 18, "price_usd": 2.0},
        }
    ),
    # Worldchain
    ChainConfig(
        name="Worldchain",
        chain_id=480,
        wss="wss://api-worldchain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-worldchain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x79a02482a880bce3f13e09da970dc34db4cd24d1": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0x2cfc85d8e48f8eab294be644d9e25c3030863003": {"symbol": "WLD", "decimals": 18, "price_usd": 2.0},
            "0x03c7054bcb39f7b2e5b2c7acb37583e32d70cfa3": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x0258f474786ddfd37abce6df6bbb1dd5dfc4434a": {"symbol": "ORB", "decimals": 18, "price_usd": 0.5},
            "0x859dbe24b90c9f2f7742083d3cf59ca41f55be5d": {"symbol": "sDAI", "decimals": 18, "price_usd": 1.0},
            "0x4200000000000000000000000000000000000042": {"symbol": "OP", "decimals": 18, "price_usd": 2.0},
            "0xdc6ff44d5d932cbd77b52e5612ba0529dc6226f1": {"symbol": "WDC", "decimals": 18, "price_usd": 0.1},
            "0x5fd84259d66cd46123540766be93dfe6d43130d7": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x7b6ee459e8a49d11bec43b85e6787f51390bc48a": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
        }
    ),
    # opBNB
    ChainConfig(
        name="opBNB",
        chain_id=204,
        wss="wss://api-opbnb-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-opbnb-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WBNB", "decimals": 18, "price_usd": 600.0},
            "0xe7798f023fc62146e8aa1b36da45fb70855a77ea": {"symbol": "ETH", "decimals": 18, "price_usd": 2500.0},
            "0x9e5aac1ba1a2e6aed6b32689dfcf62a509ca96f3": {"symbol": "USDT", "decimals": 18, "price_usd": 1.0},
            "0x7c6b91d9be155a6db01f749217d76ff02a7227f2": {"symbol": "BTCB", "decimals": 18, "price_usd": 95000.0},
            "0x1e4a5963abfd975d8c9021ce480b42188849d41d": {"symbol": "USDC", "decimals": 18, "price_usd": 1.0},
            "0x4d4e595d643dc61ea7fcbf12e4b1aaa39f9975b8": {"symbol": "FDUSD", "decimals": 18, "price_usd": 1.0},
            "0xf0c8e0f39d97923b8c2cc5a6f5d69d8a631f4d6b": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
            "0x7f0000000158c9b59cdb0c39eb7c7fd4e09adb73": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0xcfa3ef56d303ae4faaba0592388f19d7c3399fb4": {"symbol": "XRP", "decimals": 18, "price_usd": 2.5},
            "0x9c3c9283d3e44854697cd22d3faa240cfb032889": {"symbol": "MATIC", "decimals": 18, "price_usd": 0.5},
        }
    ),
    # Ronin
    ChainConfig(
        name="Ronin",
        chain_id=2020,
        wss="wss://api-ronin-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-ronin-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xe514d9deb7966c8be0ca922de8a064264ea6bcd4": {"symbol": "WRON", "decimals": 18, "price_usd": 2.0},
            "0xc99a6a985ed2cac1ef41640596c5a5f9f4e19ef5": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x97a9107c1793bc407d6f527b77e7fff4d812bece": {"symbol": "AXS", "decimals": 18, "price_usd": 7.0},
            "0xa8754b9fa15fc18bb59458815510e40a12cd2014": {"symbol": "SLP", "decimals": 0, "price_usd": 0.003},
            "0x0b7007c13325c48911f73a2dad5fa5dcbf808adc": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xc3665f2600c9f7e5d0f3f5f5f5c5c5c5c5c5c5c5": {"symbol": "PIXEL", "decimals": 18, "price_usd": 0.15},
            "0x173a2d4fa585a63acd02c107d57f932be0a71bcc": {"symbol": "BANANA", "decimals": 18, "price_usd": 0.01},
            "0x7894b3088d069e70895effb2e92b106fda8a12f3": {"symbol": "YGG", "decimals": 18, "price_usd": 0.5},
            "0x2eca41a3478b3cc61c04b20fc72c3f0a2e8f3a41": {"symbol": "BERRY", "decimals": 18, "price_usd": 0.001},
            "0xea589e93ff18b1a1f1e9bac7ef3e86ab62addc79": {"symbol": "VIS", "decimals": 18, "price_usd": 0.0001},
        }
    ),
    # LISK
    ChainConfig(
        name="LISK",
        chain_id=1135,
        wss="wss://api-lisk-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-lisk-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xac485391eb2d7d88253a7f1ef18c37f4f50fdfc4": {"symbol": "LSK", "decimals": 18, "price_usd": 1.0},
            "0x0faf8b0d8c93e18073b8ac7a04f59f91ad4c6e76": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xf242275d3a6527d877f2c927a82d9b057609cc71": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x7f8a58e0c0a9b8d13f06e67a3ff5aadb8e5e78f9": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
            "0x05d032ac25d322df992303dca074ee7392c117b9": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
            "0x4200000000000000000000000000000000000042": {"symbol": "OP", "decimals": 18, "price_usd": 2.0},
            "0x8a21cf9ba08ae709d64cb25afd8a3d5c5476e70f": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x8a892456e72d8ff7d78f8c5d3e8ed8f4b9b1a6d5": {"symbol": "AAVE", "decimals": 18, "price_usd": 250.0},
            "0x7ab1a2b3c4d5e6f7890a1b2c3d4e5f6a7b8c9d0e": {"symbol": "LINK", "decimals": 18, "price_usd": 18.0},
        }
    ),
    # Zetachain
    ChainConfig(
        name="Zetachain",
        chain_id=7000,
        wss="wss://api-zetachain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-zetachain-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x5f0b1a82749cb4e2278ec87f8bf6b618dc71a8bf": {"symbol": "WZETA", "decimals": 18, "price_usd": 0.5},
            "0xd97b1de3619ed2c6beb3860147e30ca8a7dc9891": {"symbol": "ETH.ETH", "decimals": 18, "price_usd": 2500.0},
            "0x05ba149a7bd6dc1f937fa9046a9e05c05f3b18b0": {"symbol": "USDC.ETH", "decimals": 6, "price_usd": 1.0},
            "0x7c8dda80bbbe1254a7aacf3219ebe1481c6e01d7": {"symbol": "USDT.ETH", "decimals": 6, "price_usd": 1.0},
            "0x13a0c5930c028511dc02665e7285134b6d11a5f4": {"symbol": "BTC.BTC", "decimals": 8, "price_usd": 95000.0},
            "0x48f80608b672dc30dc7e3dbbd0343c5f02c738eb": {"symbol": "BNB.BSC", "decimals": 18, "price_usd": 600.0},
            "0x0cbe0df132a6c6b4a2974fa1b7fb953cf0cc798a": {"symbol": "USDC.BSC", "decimals": 18, "price_usd": 1.0},
            "0x91d4f0d54090df2d81e834c3c8ce71c6c865e79f": {"symbol": "USDT.BSC", "decimals": 18, "price_usd": 1.0},
            "0x999a9c10f5c57cf0afa3a8c77e5c25c5c5c5c5c5": {"symbol": "MATIC.POL", "decimals": 18, "price_usd": 0.5},
            "0x7f5c764cbc14f9669b88837ca1490cca17c31607": {"symbol": "stZETA", "decimals": 18, "price_usd": 0.5},
        }
    ),
    # Chiliz
    ChainConfig(
        name="Chiliz",
        chain_id=88888,
        wss="wss://api-chiliz-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-chiliz-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x677f7e16c7dd57be1d4c8ad1244883214953dc47": {"symbol": "WCHZ", "decimals": 18, "price_usd": 0.08},
            "0x721ef6871f1c4efe730dce047f40d1433b184a14": {"symbol": "PEPPER", "decimals": 18, "price_usd": 0.0001},
            "0x6b175474e89094c44da98b954eedeac495271d0f": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xdac17f958d2ee523a2206206994597c13d831ec7": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
        }
    ),
    # Flow EVM
    ChainConfig(
        name="Flow",
        chain_id=747,
        wss="wss://api-flow-evm-gateway-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-flow-evm-gateway-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xd3bfd5a7cef3bce8e3e1f57f12f6f3a4f073d1e7": {"symbol": "WFLOW", "decimals": 18, "price_usd": 0.7},
            "0x1b97100ea1d7126c4d60027e231ea4cb25314bdb": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x674ffdc90cf5ec7d021ea44e8c9e99f6ffc01ecc": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x2b4ef8e0be71a2f3c3e9f6f0e8e8e8e8e8e8e8e8": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x3b4ef8e0be71a2f3c3e9f6f0e8e8e8e8e8e8e8e8": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Hyperliquid EVM
    ChainConfig(
        name="Hyperliquid",
        chain_id=998,
        wss="wss://api-hyperliquid-mainnet-evm.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-hyperliquid-mainnet-evm.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x0000000000000000000000000000000000000000": {"symbol": "HYPE", "decimals": 18, "price_usd": 25.0},
            "0xeb62eee3685fc588d5c4a3f345d4a5a44e6e62d4": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x2f6f07cdcf3588944bf4c42ac74ff24bf56e7590": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x4d4e595d643dc61ea7fcbf12e4b1aaa39f9975b8": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x5979d7b546e38e414f7e9822514be443a4800529": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Iotex
    ChainConfig(
        name="Iotex",
        chain_id=4689,
        wss="wss://api-iotex-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-iotex-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xa00744882684c3e4747faefd68d283ea44099d03": {"symbol": "WIOTX", "decimals": 18, "price_usd": 0.02},
            "0x84abcb2832be606341a50128aeb1db43aa017449": {"symbol": "BUSD", "decimals": 18, "price_usd": 1.0},
            "0x6fbcdc1169b5130c59e72e51ed68a84841c98cd1": {"symbol": "ioUSDT", "decimals": 6, "price_usd": 1.0},
            "0x3b2bf2b523f54c4e454f08aa286d03115aff326c": {"symbol": "ioUSDC", "decimals": 6, "price_usd": 1.0},
            "0x0258866edaf84d6081df17660357ab20a07d0c80": {"symbol": "ioETH", "decimals": 18, "price_usd": 2500.0},
        }
    ),
    # Manta Pacific
    ChainConfig(
        name="Manta",
        chain_id=169,
        wss="wss://api-manta-pacific-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-manta-pacific-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x0dc808adce2099a9f62aa87d9670745aba741746": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xb73603c5d87fa094b7314c74ace2e64d165016fb": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xf417f5a458ec102b90352f697d6e2ac3a3d2851f": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x95cef13441be50d20ca4558cc0a27b601ac544e5": {"symbol": "MANTA", "decimals": 18, "price_usd": 1.0},
            "0x305e88d809c9dc03179554bfbf85ac05ce8f18d6": {"symbol": "wstETH", "decimals": 18, "price_usd": 2900.0},
        }
    ),
    # MegaETH
    ChainConfig(
        name="MegaETH",
        chain_id=6342,
        wss="wss://api-megaeth-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-megaeth-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
            "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Monad
    ChainConfig(
        name="Monad",
        chain_id=10143,
        wss="wss://api-monad-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-monad-mainnet-full.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WMON", "decimals": 18, "price_usd": 1.0},
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Mythos
    ChainConfig(
        name="Mythos",
        chain_id=7001,
        wss="wss://api-mythos-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-mythos-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x4200000000000000000000000000000000000006": {"symbol": "WMYTH", "decimals": 18, "price_usd": 0.1},
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": {"symbol": "WBTC", "decimals": 8, "price_usd": 95000.0},
        }
    ),
    # Viction
    ChainConfig(
        name="Viction",
        chain_id=88,
        wss="wss://api-viction-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-viction-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xc054751bdbd24ae713ba3dc9bd9434abe2abc1ce": {"symbol": "WVIC", "decimals": 18, "price_usd": 0.5},
            "0x381b31409e4d220919b2cff012ed94d70135a59e": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x20ccc4c9a3b1daa2c3875e93e4951b69cf5eb58b": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x2eaa73bd0db20c64f53febea7b5f5e5bccc7fb8b": {"symbol": "ETH", "decimals": 18, "price_usd": 2500.0},
            "0xb1f66997a5760428d3a87d68b90bfe0ae64121cc": {"symbol": "LUA", "decimals": 18, "price_usd": 0.001},
        }
    ),
    # XDC
    ChainConfig(
        name="XDC",
        chain_id=50,
        wss="wss://api-xdc-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        rpc_url="https://api-xdc-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x951857744785e80e2de051c32ee7b25f9c458c42": {"symbol": "WXDC", "decimals": 18, "price_usd": 0.03},
            "0xc3953e2e9e91bf5a4a80c2e59e9c41413a8f4ed9": {"symbol": "xUSDT", "decimals": 6, "price_usd": 1.0},
            "0x49d3f7543335cf38fa10889ccff10207e22110b5": {"symbol": "xUSDC", "decimals": 6, "price_usd": 1.0},
            "0x8a7a5d5818e7a0bce3c7e91d1cbf01ec75b0f678": {"symbol": "xETH", "decimals": 18, "price_usd": 2500.0},
            "0x70a1a8f6b90e0b6c5f8c7a8f9e8f0d1c2b3a4e5f": {"symbol": "PLI", "decimals": 18, "price_usd": 0.05},
        }
    ),
    # Avalanche C-Chain (HTTPS only - no WSS available)
    ChainConfig(
        name="Avalanche",
        chain_id=43114,
        rpc_url="https://api-avalanche-mainnet-archive.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400/ext/bc/C/rpc",
        tokens={
            "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7": {"symbol": "WAVAX", "decimals": 18, "price_usd": 25.0},
            "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0x49d5c2bdffac6ce2bfdb6640f4f80f226bc10bab": {"symbol": "WETH.e", "decimals": 18, "price_usd": 2500.0},
            "0x50b7545627a5162f82a992c33b87adc75187b218": {"symbol": "WBTC.e", "decimals": 8, "price_usd": 95000.0},
            "0xd586e7f844cea2f87f50152665bcbc2c279d8d70": {"symbol": "DAI.e", "decimals": 18, "price_usd": 1.0},
            "0x2b2c81e08f1af8835a78bb2a90ae924ace0ea4be": {"symbol": "sAVAX", "decimals": 18, "price_usd": 27.0},
            "0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664": {"symbol": "USDC.e", "decimals": 6, "price_usd": 1.0},
            "0x152b9d0fdc40c096de345726606e39f0957e02ef": {"symbol": "BTCb", "decimals": 8, "price_usd": 95000.0},
            "0x5947bb275c521040051d82396192181b413227a3": {"symbol": "LINK.e", "decimals": 18, "price_usd": 18.0},
        },
        poll_interval=2.0,
    ),
    # Boba (HTTPS only - no WSS available)
    ChainConfig(
        name="Boba",
        chain_id=288,
        rpc_url="https://api-boba-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0x66a2a913e447d6b4bf33efbec43aaef87890fbbc": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x5de1677344d3cb0d7d465c10b72a8f60699c062d": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
            "0xa18bf3994c0cc6e3b63ac420308e5383f53120d7": {"symbol": "BOBA", "decimals": 18, "price_usd": 0.3},
            "0xf74195bb8a5cf652411867c5c2c5b8c2a402be35": {"symbol": "DAI", "decimals": 18, "price_usd": 1.0},
        },
        poll_interval=5.0,
    ),
    # Immutable zkEVM (HTTPS only - no WSS available)
    ChainConfig(
        name="Immutable",
        chain_id=13371,
        rpc_url="https://api-immutable-zkevm-mainnet.n.dwellir.com/e5433693-bdd2-4168-851b-acaf16f10400",
        tokens={
            "0x3a0c2ba54d6cbd3121d49968c9e3658e05dbbf58": {"symbol": "WIMX", "decimals": 18, "price_usd": 1.5},
            "0x6de8acc0d406837030ce4dd28e7c08c5a96a30d2": {"symbol": "USDC", "decimals": 6, "price_usd": 1.0},
            "0x52a6c53869ce09a731cd772f245b97a4401d3348": {"symbol": "WETH", "decimals": 18, "price_usd": 2500.0},
            "0xbf7f0f4cbc27ddf9dcefdd58c094f2014e0c77c0": {"symbol": "GOG", "decimals": 18, "price_usd": 0.05},
            "0xa44151489861fe9e3055d95adc98fbd462b948e7": {"symbol": "USDT", "decimals": 6, "price_usd": 1.0},
        },
        poll_interval=3.0,
    ),
]


# HTTP session for webhooks (will be created in main)
http_session: Optional[aiohttp.ClientSession] = None


def decode_transfer_log(log: dict) -> Optional[dict]:
    """Decode a Transfer event log."""
    try:
        topics = log.get("topics", [])
        if len(topics) < 3:
            return None

        sender = "0x" + topics[1][-40:]
        recipient = "0x" + topics[2][-40:]

        data = log.get("data", "0x0")
        amount_raw = int(data, 16) if data and data != "0x" else 0

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
        return None


def calculate_usd_value(tokens: Dict, contract: str, amount_raw: int) -> Optional[tuple]:
    """Calculate USD value of a transfer. Returns (usd_value, symbol) or None."""
    contract_lower = contract.lower()

    if contract_lower not in tokens:
        return None

    token_info = tokens[contract_lower]
    decimals = token_info["decimals"]
    price = token_info["price_usd"]

    amount = Decimal(amount_raw) / Decimal(10 ** decimals)
    usd_value = float(amount) * price

    return (usd_value, token_info["symbol"])


async def send_to_webhook(chain: ChainConfig, transfer: dict, usd_value: float, symbol: str):
    """Send transfer data to all webhook endpoints with chain info."""
    global http_session

    payload = {
        "r": transfer["recipient"],
        "s": transfer["sender"],
        "contract": transfer["contract"],
        "chain_id": chain.chain_id,
        "wss": chain.wss or "",
        "rpc_url": chain.rpc_url,
    }

    # Print payload to terminal
    print(f"\n[{chain.name}] {symbol} ${usd_value:,.2f}")
    print(f"  TX: {transfer.get('tx_hash', 'N/A')}")
    print(f"  JSON: {json.dumps(payload)}")

    for url in WEBHOOK_URLS:
        try:
            async with http_session.post(url, json=payload, timeout=5) as response:
                status = response.status
                dest = "webhook.site" if "webhook.site" in url else "local"
                print(f"  -> {dest}: HTTP {status}")
        except Exception as e:
            dest = "webhook.site" if "webhook.site" in url else "local"
            print(f"  -> {dest}: ERROR {e}")


async def monitor_chain(chain: ChainConfig):
    """Monitor a single chain for token transfers."""
    global http_session

    # Normalize token addresses to lowercase
    tokens = {k.lower(): v for k, v in chain.tokens.items()}

    while True:
        try:
            print(f"[{chain.name}] Connecting to {chain.wss[:50]}...")
            async with websockets.connect(chain.wss, ping_interval=30, ping_timeout=10) as ws:
                print(f"[{chain.name}] Connected! Subscribing to {len(tokens)} tokens...")

                subscribe_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": [
                        "logs",
                        {
                            "address": list(tokens.keys()),
                            "topics": [TRANSFER_TOPIC]
                        }
                    ]
                }

                await ws.send(json.dumps(subscribe_request))
                response = await ws.recv()
                result = json.loads(response)

                if "result" in result:
                    print(f"[{chain.name}] Subscribed! ID: {result['result'][:16]}...")
                else:
                    print(f"[{chain.name}] Subscription failed: {result}")
                    await asyncio.sleep(10)
                    continue

                async for message in ws:
                    try:
                        data = json.loads(message)

                        if "params" not in data:
                            continue

                        log = data["params"]["result"]
                        transfer = decode_transfer_log(log)

                        if not transfer:
                            continue

                        result = calculate_usd_value(tokens, transfer["contract"], transfer["amount_raw"])

                        if result is None:
                            continue

                        usd_value, symbol = result

                        if usd_value >= MIN_USD_VALUE:
                            await send_to_webhook(chain, transfer, usd_value, symbol)

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        continue

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[{chain.name}] Connection closed: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[{chain.name}] Error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)


async def monitor_chain_http(chain: ChainConfig):
    """Monitor a chain for token transfers via HTTP polling (for chains without WSS)."""
    global http_session

    tokens = {k.lower(): v for k, v in chain.tokens.items()}
    last_block = None

    print(f"[{chain.name}] Starting HTTP polling (interval: {chain.poll_interval}s)...")

    while True:
        try:
            # Get current block number
            block_req = {
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_blockNumber", "params": []
            }
            async with http_session.post(chain.rpc_url, json=block_req, timeout=10) as resp:
                block_result = await resp.json()
                current_block = block_result.get("result")

            if not current_block:
                await asyncio.sleep(chain.poll_interval)
                continue

            if last_block is None:
                print(f"[{chain.name}] HTTP poll started at block {current_block}")
                last_block = current_block
                await asyncio.sleep(chain.poll_interval)
                continue

            from_block = hex(int(last_block, 16) + 1)
            if int(from_block, 16) > int(current_block, 16):
                await asyncio.sleep(chain.poll_interval)
                continue

            # Get transfer logs for new blocks
            log_req = {
                "jsonrpc": "2.0", "id": 2,
                "method": "eth_getLogs",
                "params": [{
                    "fromBlock": from_block,
                    "toBlock": current_block,
                    "address": list(tokens.keys()),
                    "topics": [TRANSFER_TOPIC]
                }]
            }
            async with http_session.post(chain.rpc_url, json=log_req, timeout=30) as resp:
                log_result = await resp.json()

            logs = log_result.get("result", [])
            if isinstance(logs, list):
                for log in logs:
                    transfer = decode_transfer_log(log)
                    if not transfer:
                        continue
                    val = calculate_usd_value(tokens, transfer["contract"], transfer["amount_raw"])
                    if val is None:
                        continue
                    usd_value, symbol = val
                    if usd_value >= MIN_USD_VALUE:
                        await send_to_webhook(chain, transfer, usd_value, symbol)

            last_block = current_block
            await asyncio.sleep(chain.poll_interval)

        except Exception as e:
            print(f"[{chain.name}] HTTP poll error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)


async def main():
    """Main entry point."""
    global http_session

    wss_chains = [c for c in CHAINS if c.wss]
    http_chains = [c for c in CHAINS if not c.wss]

    print("=" * 70)
    print("Multi-Chain Token Transfer Monitor")
    print(f"Webhooks: {len(WEBHOOK_URLS)}")
    print(f"Min Value: ${MIN_USD_VALUE}")
    print(f"Chains: {len(CHAINS)} ({len(wss_chains)} WSS + {len(http_chains)} HTTP)")
    print("=" * 70)

    # Create HTTP session
    http_session = aiohttp.ClientSession()

    try:
        # Start all chain monitors concurrently
        tasks = []
        for chain in CHAINS:
            if chain.wss:
                tasks.append(monitor_chain(chain))
            else:
                tasks.append(monitor_chain_http(chain))
        await asyncio.gather(*tasks)
    finally:
        await http_session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
