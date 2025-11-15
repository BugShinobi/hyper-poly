"""
Hyperliquid client for perpetual futures trading
"""
import asyncio
import json
import time
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal
from datetime import datetime
import aiohttp
import websockets
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
import hashlib
import hmac

from src.models import (
    SpotMarket,
    MarketSide,
    OrderType,
    PriceLevel
)
from src.config import config
from src.utils.logger import bot_logger


class HyperliquidClient:
    """Client for interacting with Hyperliquid DEX"""
    
    # Hyperliquid endpoints
    MAINNET_API = "https://api.hyperliquid.xyz"
    TESTNET_API = "https://api.hyperliquid-testnet.xyz"
    MAINNET_WS = "wss://api.hyperliquid.xyz/ws"
    TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws"
    
    # Asset configurations
    ASSETS = {
        "BTC": {
            "name": "BTC",
            "szDecimals": 5,  # Size decimals
            "pxDecimals": 1,  # Price decimals
            "minSize": 0.001,
            "maxLeverage": 50
        },
        "ETH": {
            "name": "ETH",
            "szDecimals": 4,
            "pxDecimals": 1,
            "minSize": 0.01,
            "maxLeverage": 50
        },
        "SOL": {
            "name": "SOL",
            "szDecimals": 3,
            "pxDecimals": 2,
            "minSize": 0.1,
            "maxLeverage": 20
        }
    }
    
    def __init__(self, is_mainnet: bool = True):
        """
        Initialize Hyperliquid client
        
        Args:
            is_mainnet: Whether to use mainnet or testnet
        """
        self.is_mainnet = is_mainnet
        self.api_url = self.MAINNET_API if is_mainnet else self.TESTNET_API
        self.ws_url = self.MAINNET_WS if is_mainnet else self.TESTNET_WS
        
        # Account setup
        self.private_key = config.HYPERLIQUID_PRIVATE_KEY
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address
        
        # Optional API wallet for trading
        self.api_wallet = config.HYPERLIQUID_API_WALLET if hasattr(config, 'HYPERLIQUID_API_WALLET') else None
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        
        # Cache for market data
        self.market_cache: Dict[str, Any] = {}
        self.funding_rates: Dict[str, Decimal] = {}
        
        bot_logger.info(f"Initialized Hyperliquid client ({'mainnet' if is_mainnet else 'testnet'})")
        bot_logger.info(f"Trading address: {self.address}")
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def close(self):
        """Close all open connections"""
        if self.session:
            await self.session.close()
        if self.ws:
            await self.ws.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        signed: bool = False
    ) -> Dict[str, Any]:
        """
        Make HTTP request to Hyperliquid API
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request data
            signed: Whether to sign the request
        
        Returns:
            Response data
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = f"{self.api_url}{endpoint}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if signed and data:
            # Sign the request
            signature = self._sign_request(data)
            data["signature"] = signature
        
        try:
            if method == "GET":
                async with self.session.get(url, params=data, headers=headers) as response:
                    return await response.json()
            elif method == "POST":
                async with self.session.post(url, json=data, headers=headers) as response:
                    return await response.json()
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
        except Exception as e:
            bot_logger.error(f"API request failed: {e}")
            return {}
    
    def _sign_request(self, data: Dict) -> str:
        """
        Sign a request with the private key
        
        Args:
            data: Request data to sign
        
        Returns:
            Signature hex string
        """
        # Hyperliquid uses EIP-712 signing
        message = json.dumps(data, sort_keys=True)
        message_hash = hashlib.sha256(message.encode()).digest()
        
        # Sign with private key
        signed_message = self.account.signHash(message_hash)
        
        return signed_message.signature.hex()
    
    def _sign_l1_action(
        self,
        action_type: str,
        nonce: int,
        action_data: Dict
    ) -> Dict:
        """
        Sign an L1 action for Hyperliquid
        
        Args:
            action_type: Type of action (order, cancel, etc.)
            nonce: Action nonce
            action_data: Action specific data
        
        Returns:
            Signed action ready to submit
        """
        # Construct the action
        action = {
            "type": action_type,
            "user": self.address,
            "nonce": nonce,
            **action_data
        }
        
        # Create signature
        signature_input = {
            "domain": {
                "name": "Hyperliquid",
                "version": "1",
                "chainId": 1337 if not self.is_mainnet else 42161,  # Arbitrum mainnet
                "verifyingContract": "0x0000000000000000000000000000000000000000"
            },
            "types": {
                "Action": [
                    {"name": "type", "type": "string"},
                    {"name": "user", "type": "address"},
                    {"name": "nonce", "type": "uint64"}
                ]
            },
            "primaryType": "Action",
            "message": action
        }
        
        # Sign the structured data
        encoded = encode_defunct(json.dumps(signature_input))
        signed = self.account.sign_message(encoded)
        
        return {
            "action": action,
            "signature": signed.signature.hex()
        }
    
    async def get_account_state(self) -> Dict[str, Any]:
        """Get account state including balances and positions"""
        try:
            data = {
                "type": "clearinghouseState",
                "user": self.address
            }
            
            response = await self._make_request("POST", "/info", data)
            return response
            
        except Exception as e:
            bot_logger.error(f"Error getting account state: {e}")
            return {}
    
    async def get_market_data(self, asset: str) -> Optional[SpotMarket]:
        """
        Get current market data for an asset
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
        
        Returns:
            SpotMarket data
        """
        try:
            # Get meta info for all assets
            meta_response = await self._make_request("POST", "/info", {"type": "meta"})
            
            # Find the asset
            asset_info = None
            for universe in meta_response.get("universe", []):
                if universe["name"] == asset:
                    asset_info = universe
                    break
            
            if not asset_info:
                bot_logger.error(f"Asset {asset} not found on Hyperliquid")
                return None
            
            # Get current prices
            prices_response = await self._make_request(
                "POST",
                "/info",
                {"type": "allMids"}
            )
            
            # Get order book for better bid/ask
            orderbook_response = await self._make_request(
                "POST",
                "/info",
                {
                    "type": "l2Book",
                    "coin": asset
                }
            )
            
            # Parse data
            asset_index = asset_info.get("index", 0)
            current_price = Decimal(prices_response.get("mids", [{}])[asset_index])
            
            orderbook = orderbook_response.get("levels", {})
            best_bid = Decimal(orderbook[0][0]["px"]) if orderbook else current_price * Decimal("0.999")
            best_ask = Decimal(orderbook[1][0]["px"]) if orderbook and len(orderbook) > 1 else current_price * Decimal("1.001")
            
            # Get funding rate
            funding_response = await self._make_request(
                "POST",
                "/info",
                {"type": "fundingHistory", "coin": asset, "startTime": int(time.time() * 1000) - 86400000}
            )
            
            if funding_response:
                latest_funding = funding_response[-1] if funding_response else {}
                self.funding_rates[asset] = Decimal(latest_funding.get("fundingRate", "0"))
            
            return SpotMarket(
                exchange="hyperliquid",
                symbol=f"{asset}-USD-PERP",
                bid=best_bid,
                ask=best_ask,
                last=current_price,
                volume_24h=Decimal(asset_info.get("dayVolume", "0"))
            )
            
        except Exception as e:
            bot_logger.error(f"Error fetching market data: {e}")
            return None
    
    async def get_order_book(self, asset: str, depth: int = 20) -> Dict[str, List[PriceLevel]]:
        """
        Get order book for an asset
        
        Args:
            asset: Asset symbol
            depth: Number of price levels
        
        Returns:
            Dictionary with 'bids' and 'asks'
        """
        try:
            response = await self._make_request(
                "POST",
                "/info",
                {
                    "type": "l2Book",
                    "coin": asset,
                    "nLevels": depth
                }
            )
            
            levels = response.get("levels", [[],[]])
            
            bids = [
                PriceLevel(
                    price=Decimal(level["px"]),
                    quantity=Decimal(level["sz"])
                )
                for level in levels[0][:depth]
            ] if levels and len(levels) > 0 else []
            
            asks = [
                PriceLevel(
                    price=Decimal(level["px"]),
                    quantity=Decimal(level["sz"])
                )
                for level in levels[1][:depth]
            ] if levels and len(levels) > 1 else []
            
            return {"bids": bids, "asks": asks}
            
        except Exception as e:
            bot_logger.error(f"Error fetching order book: {e}")
            return {"bids": [], "asks": []}
    
    async def place_order(
        self,
        asset: str,
        side: MarketSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        leverage: int = None,
        reduce_only: bool = False,
        post_only: bool = False
    ) -> Optional[str]:
        """
        Place an order on Hyperliquid
        
        Args:
            asset: Asset to trade
            side: LONG or SHORT
            order_type: MARKET or LIMIT
            quantity: Order quantity
            price: Limit price
            leverage: Leverage to use
            reduce_only: Whether this is reduce-only
            post_only: Maker-only order
        
        Returns:
            Order ID if successful
        """
        try:
            # Get asset configuration
            asset_config = self.ASSETS.get(asset)
            if not asset_config:
                bot_logger.error(f"Asset {asset} not supported")
                return None
            
            # Set leverage if provided
            if leverage and not reduce_only:
                await self.set_leverage(asset, leverage)
            
            # Get nonce
            nonce = int(time.time() * 1000)
            
            # Round size and price according to asset decimals
            quantity = round(float(quantity), asset_config["szDecimals"])
            
            # Determine order price
            if order_type == OrderType.MARKET:
                # For market orders, use a limit price with slippage
                market_data = await self.get_market_data(asset)
                if side == MarketSide.LONG:
                    price = float(market_data.ask * Decimal("1.01"))  # 1% slippage
                else:
                    price = float(market_data.bid * Decimal("0.99"))
            
            price = round(float(price), asset_config["pxDecimals"])
            
            # Create order
            order_data = {
                "coin": asset,
                "is_buy": side == MarketSide.LONG,
                "sz": quantity,
                "limit_px": price,
                "order_type": {
                    "limit": {
                        "tif": "Ioc" if order_type == OrderType.MARKET else "Gtc"
                    }
                },
                "reduce_only": reduce_only,
                "grouping": "na"
            }
            
            # Sign and submit order
            signed_order = self._sign_l1_action("order", nonce, order_data)
            
            response = await self._make_request(
                "POST",
                "/exchange",
                signed_order,
                signed=True
            )
            
            if response.get("status") == "ok":
                order_id = response.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("resting", {}).get("oid")
                
                bot_logger.info(
                    f"Placed {side.value} order for {quantity} {asset} at {price} - Order ID: {order_id}",
                    extra={"trade": True}
                )
                return order_id
            else:
                bot_logger.error(f"Failed to place order: {response}")
                return None
                
        except Exception as e:
            bot_logger.error(f"Error placing order: {e}")
            return None
    
    async def cancel_order(self, asset: str, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            nonce = int(time.time() * 1000)
            
            cancel_data = {
                "coin": asset,
                "oid": order_id
            }
            
            signed_cancel = self._sign_l1_action("cancel", nonce, cancel_data)
            
            response = await self._make_request(
                "POST",
                "/exchange",
                signed_cancel,
                signed=True
            )
            
            if response.get("status") == "ok":
                bot_logger.info(f"Cancelled order: {order_id}")
                return True
            return False
            
        except Exception as e:
            bot_logger.error(f"Error cancelling order: {e}")
            return False
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions"""
        try:
            state = await self.get_account_state()
            positions = state.get("assetPositions", [])
            
            formatted_positions = []
            for i, pos in enumerate(positions):
                if pos.get("position", {}).get("szi", "0") != "0":
                    formatted_positions.append({
                        "coin": state.get("assets", [])[i].get("name"),
                        "size": Decimal(pos["position"]["szi"]),
                        "entry_price": Decimal(pos["position"]["entryPx"]),
                        "unrealized_pnl": Decimal(pos["position"]["unrealizedPnl"]),
                        "margin_used": Decimal(pos["position"]["marginUsed"]),
                        "leverage": int(Decimal(pos["position"]["leverage"]))
                    })
            
            return formatted_positions
            
        except Exception as e:
            bot_logger.error(f"Error getting positions: {e}")
            return []
    
    async def get_balance(self) -> Decimal:
        """Get account balance in USD"""
        try:
            state = await self.get_account_state()
            
            # Get total account value
            account_value = Decimal(state.get("clearinghouseState", {}).get("marginSummary", {}).get("accountValue", "0"))
            
            bot_logger.info(f"Account balance: ${account_value:.2f}")
            return account_value
            
        except Exception as e:
            bot_logger.error(f"Error getting balance: {e}")
            return Decimal(0)
    
    async def set_leverage(self, asset: str, leverage: int) -> bool:
        """
        Set leverage for an asset
        
        Args:
            asset: Asset to set leverage for
            leverage: Leverage (1-50)
        
        Returns:
            Success status
        """
        try:
            if leverage < 1 or leverage > 50:
                bot_logger.error(f"Invalid leverage: {leverage} (must be 1-50)")
                return False
            
            nonce = int(time.time() * 1000)
            
            leverage_data = {
                "coin": asset,
                "leverage": leverage,
                "is_cross": True  # Use cross margin
            }
            
            signed_action = self._sign_l1_action("updateLeverage", nonce, leverage_data)
            
            response = await self._make_request(
                "POST",
                "/exchange",
                signed_action,
                signed=True
            )
            
            if response.get("status") == "ok":
                bot_logger.info(f"Set leverage to {leverage}x for {asset}")
                return True
            return False
            
        except Exception as e:
            bot_logger.error(f"Error setting leverage: {e}")
            return False
    
    async def get_funding_rate(self, asset: str) -> Decimal:
        """Get current funding rate for an asset"""
        return self.funding_rates.get(asset, Decimal(0))
    
    async def get_open_orders(self, asset: Optional[str] = None) -> List[Dict]:
        """Get all open orders"""
        try:
            state = await self.get_account_state()
            orders = state.get("clearinghouseState", {}).get("openOrders", [])
            
            if asset:
                orders = [o for o in orders if o.get("coin") == asset]
            
            return orders
            
        except Exception as e:
            bot_logger.error(f"Error getting open orders: {e}")
            return []
    
    async def close_position(self, asset: str) -> bool:
        """
        Close entire position for an asset
        
        Args:
            asset: Asset to close position for
        
        Returns:
            Success status
        """
        try:
            positions = await self.get_positions()
            
            for pos in positions:
                if pos["coin"] == asset and pos["size"] != 0:
                    # Determine side to close position
                    close_side = MarketSide.SHORT if pos["size"] > 0 else MarketSide.LONG
                    
                    # Place market order to close
                    order_id = await self.place_order(
                        asset=asset,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=abs(pos["size"]),
                        reduce_only=True
                    )
                    
                    if order_id:
                        bot_logger.info(f"Closed position for {asset}")
                        return True
            
            return False
            
        except Exception as e:
            bot_logger.error(f"Error closing position: {e}")
            return False
    
    async def subscribe_to_market_data(self, assets: List[str], callback):
        """
        Subscribe to real-time market data via WebSocket
        
        Args:
            assets: List of assets to subscribe to
            callback: Async callback function for updates
        """
        try:
            async with websockets.connect(self.ws_url) as websocket:
                self.ws = websocket
                
                # Subscribe to each asset
                for asset in assets:
                    subscribe_msg = {
                        "method": "subscribe",
                        "subscription": {
                            "type": "l2Book",
                            "coin": asset
                        }
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    
                    # Also subscribe to trades
                    trades_msg = {
                        "method": "subscribe",
                        "subscription": {
                            "type": "trades",
                            "coin": asset
                        }
                    }
                    await websocket.send(json.dumps(trades_msg))
                
                # Listen for updates
                async for message in websocket:
                    data = json.loads(message)
                    await callback(data)
                    
        except Exception as e:
            bot_logger.error(f"WebSocket error: {e}")
            self.ws = None
    
    def calculate_liquidation_price(
        self,
        entry_price: Decimal,
        side: MarketSide,
        leverage: int
    ) -> Decimal:
        """
        Calculate liquidation price for a position
        
        Args:
            entry_price: Entry price
            side: Position side
            leverage: Position leverage
        
        Returns:
            Liquidation price
        """
        # Hyperliquid maintenance margin is 0.6%
        maintenance_margin = Decimal("0.006")
        
        if side == MarketSide.LONG:
            # Long liquidation
            liquidation_price = entry_price * (1 - (1 - maintenance_margin) / leverage)
        else:
            # Short liquidation
            liquidation_price = entry_price * (1 + (1 - maintenance_margin) / leverage)
        
        return liquidation_price
    
    async def get_historical_funding(self, asset: str, days: int = 7) -> List[Dict]:
        """Get historical funding rates"""
        try:
            start_time = int((time.time() - (days * 86400)) * 1000)
            
            response = await self._make_request(
                "POST",
                "/info",
                {
                    "type": "fundingHistory",
                    "coin": asset,
                    "startTime": start_time
                }
            )
            
            return response
            
        except Exception as e:
            bot_logger.error(f"Error getting funding history: {e}")
            return []
