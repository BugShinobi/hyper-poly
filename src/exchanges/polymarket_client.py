"""
Polymarket client for interacting with the prediction market
"""
import asyncio
import json
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
import aiohttp
from web3 import Web3
from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.order_builder.constants import BUY, SELL
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport

from src.models import (
    PolymarketMarket, 
    MarketSide, 
    OrderType,
    PriceLevel
)
from src.config import config
from src.utils.logger import bot_logger


class PolymarketClient:
    """Client for interacting with Polymarket"""
    
    # Polymarket API endpoints
    CLOB_API_URL = "https://clob.polymarket.com"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    STRAPI_API_URL = "https://strapi-matic.poly.market"
    GRAPHQL_URL = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets"
    
    def __init__(self):
        """Initialize Polymarket client"""
        self.api_key = config.POLYMARKET_API_KEY
        self.api_secret = config.POLYMARKET_API_SECRET
        self.private_key = config.POLYMARKET_PRIVATE_KEY
        self.chain_id = config.POLYMARKET_CHAIN_ID
        
        # Initialize Web3
        self.w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address
        
        # Initialize CLOB client (updated for new py-clob-client API)
        self.clob_client = ClobClient(
            host=self.CLOB_API_URL,
            key=self.private_key,
            chain_id=self.chain_id
        )
        
        # GraphQL client for market data (deprecated - keeping for legacy functions)
        # transport = AIOHTTPTransport(url=self.GRAPHQL_URL)
        # self.gql_client = Client(transport=transport, fetch_schema_from_transport=True)

        self.session: Optional[aiohttp.ClientSession] = None
        
        bot_logger.info(f"Initialized Polymarket client for address: {self.address}")
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def get_markets_by_asset(self, asset: str = "BTC") -> List[PolymarketMarket]:
        """
        Get all active up/down markets for a specific asset using Gamma API

        Args:
            asset: Asset symbol (BTC, ETH, etc.)

        Returns:
            List of Polymarket markets
        """
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            # Use Gamma API for market data
            url = f"{self.GAMMA_API_URL}/markets"

            params = {
                "active": "true",
                "limit": 100,
                "offset": 0
            }

            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    bot_logger.error(f"Failed to fetch markets: HTTP {response.status}")
                    return []

                data = await response.json()
                markets = []

                # Filter for markets containing the asset
                for market_data in data:
                    question = market_data.get("question", "").lower()

                    # Look for price prediction markets for this asset
                    if asset.lower() in question:
                        if any(kw in question for kw in ["up", "down", "above", "below", "price", "$"]):
                            market = self._parse_rest_market_data(market_data, asset)
                            if market:
                                markets.append(market)

                bot_logger.info(f"Found {len(markets)} active {asset} markets")
                return markets

        except Exception as e:
            bot_logger.error(f"Error fetching markets: {e}")
            return []

    def _parse_rest_market_data(self, data: Dict, asset: str) -> Optional[PolymarketMarket]:
        """Parse REST API market data into PolymarketMarket model"""
        try:
            import re
            question = data.get("question", "")

            # Extract target price from question
            price_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', question)
            if not price_match:
                return None

            target_price = Decimal(price_match.group(1).replace(",", ""))

            # Get market tokens (outcomes)
            tokens = data.get("tokens", [])
            if len(tokens) < 2:
                return None

            # Determine which is up and which is down
            outcomes = [t.get("outcome", "") for t in tokens]
            up_idx = 0 if any(word in outcomes[0].lower() for word in ["yes", "up", "above"]) else 1
            down_idx = 1 - up_idx

            # Get current prices
            up_price = Decimal(str(tokens[up_idx].get("price", "0.5")))
            down_price = Decimal(str(tokens[down_idx].get("price", "0.5")))

            # Parse expiry
            end_date = data.get("endDate", data.get("end_date_iso"))
            if end_date:
                from dateutil import parser
                expiry_time = parser.parse(end_date)
            else:
                expiry_time = datetime.utcnow() + timedelta(days=1)

            return PolymarketMarket(
                market_id=data.get("condition_id", data.get("id")),
                question=question,
                asset=asset,
                target_price=target_price,
                expiry_time=expiry_time,
                up_price=up_price,
                down_price=down_price,
                up_liquidity=Decimal(str(data.get("liquidity", 0))) / 2,
                down_liquidity=Decimal(str(data.get("liquidity", 0))) / 2,
                volume_24h=Decimal(str(data.get("volume", 0))),
                open_interest=Decimal(str(data.get("volume", 0)))
            )

        except Exception as e:
            bot_logger.debug(f"Failed to parse market: {e}")
            return None
    
    def _parse_market_data(self, data: Dict, asset: str) -> Optional[PolymarketMarket]:
        """Parse raw market data into PolymarketMarket model"""
        try:
            # Extract target price from question
            question = data["question"]
            if "up or down" not in question.lower():
                return None
            
            # Parse target price (this is simplified - you'd need better parsing)
            import re
            price_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', question)
            if not price_match:
                return None
            
            target_price = Decimal(price_match.group(1).replace(",", ""))
            
            # Parse outcome prices
            outcome_prices = data["outcomePrices"]
            if len(outcome_prices) != 2:
                return None
            
            # Determine which is up and which is down based on outcomes
            outcomes = data["outcomes"]
            up_idx = 0 if "up" in outcomes[0].lower() else 1
            down_idx = 1 - up_idx
            
            return PolymarketMarket(
                market_id=data["id"],
                question=question,
                asset=asset,
                target_price=target_price,
                expiry_time=datetime.fromtimestamp(int(data["endTime"])),
                up_price=Decimal(outcome_prices[up_idx]),
                down_price=Decimal(outcome_prices[down_idx]),
                up_liquidity=Decimal(data["liquidityUSD"]) / 2,  # Simplified
                down_liquidity=Decimal(data["liquidityUSD"]) / 2,  # Simplified
                volume_24h=Decimal(data["volumeUSD"]),
                open_interest=Decimal(data["openInterestUSD"])
            )
            
        except Exception as e:
            bot_logger.warning(f"Failed to parse market data: {e}")
            return None
    
    async def get_order_book(self, market_id: str, outcome: str = "UP") -> Dict[str, List[PriceLevel]]:
        """
        Get order book for a specific market outcome
        
        Args:
            market_id: Polymarket market ID
            outcome: "UP" or "DOWN"
        
        Returns:
            Dictionary with 'bids' and 'asks' price levels
        """
        try:
            # Get order book from CLOB API
            outcome_token = self._get_outcome_token(market_id, outcome)
            order_book = self.clob_client.get_order_book(outcome_token)
            
            # Parse order book
            bids = [
                PriceLevel(
                    price=Decimal(str(bid["price"])),
                    quantity=Decimal(str(bid["size"]))
                )
                for bid in order_book.get("bids", [])
            ]
            
            asks = [
                PriceLevel(
                    price=Decimal(str(ask["price"])),
                    quantity=Decimal(str(ask["size"]))
                )
                for ask in order_book.get("asks", [])
            ]
            
            return {"bids": bids, "asks": asks}
            
        except Exception as e:
            bot_logger.error(f"Error fetching order book: {e}")
            return {"bids": [], "asks": []}
    
    def _get_outcome_token(self, market_id: str, outcome: str) -> str:
        """Get outcome token address for a market"""
        # This would need proper implementation based on Polymarket's structure
        # For now, returning a placeholder
        return f"{market_id}_{outcome}"
    
    async def place_order(
        self,
        market_id: str,
        side: MarketSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None
    ) -> Optional[str]:
        """
        Place an order on Polymarket
        
        Args:
            market_id: Market ID
            side: UP or DOWN
            order_type: MARKET or LIMIT
            quantity: Order quantity in shares
            price: Limit price (required for LIMIT orders)
        
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            # Determine buy/sell based on side
            is_buy = side == MarketSide.UP
            outcome_token = self._get_outcome_token(market_id, side.value)
            
            # Build order
            if order_type == OrderType.MARKET:
                # For market orders, use best available price
                order_book = await self.get_order_book(market_id, side.value)
                if is_buy:
                    if not order_book["asks"]:
                        bot_logger.error("No asks available for market buy")
                        return None
                    price = order_book["asks"][0].price * Decimal("1.01")  # Add 1% buffer
                else:
                    if not order_book["bids"]:
                        bot_logger.error("No bids available for market sell")
                        return None
                    price = order_book["bids"][0].price * Decimal("0.99")  # Subtract 1% buffer
            
            # Create order through CLOB client
            order = {
                "market": market_id,
                "outcome_token": outcome_token,
                "side": BUY if is_buy else SELL,
                "size": float(quantity),
                "price": float(price),
                "order_type": "GTC"  # Good till cancelled
            }
            
            # Sign and submit order
            signed_order = self.clob_client.create_order(order)
            result = self.clob_client.post_order(signed_order)
            
            order_id = result.get("orderID")
            if order_id:
                bot_logger.info(
                    f"Placed {side.value} order for {quantity} shares at {price} - Order ID: {order_id}",
                    extra={"trade": True}
                )
                return order_id
            else:
                bot_logger.error(f"Failed to place order: {result}")
                return None
                
        except Exception as e:
            bot_logger.error(f"Error placing order: {e}")
            return None
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of a specific order"""
        try:
            return self.clob_client.get_order(order_id)
        except Exception as e:
            bot_logger.error(f"Error getting order status: {e}")
            return {}
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            result = self.clob_client.cancel_order(order_id)
            success = result.get("success", False)
            if success:
                bot_logger.info(f"Cancelled order: {order_id}")
            return success
        except Exception as e:
            bot_logger.error(f"Error cancelling order: {e}")
            return False
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions for the account"""
        try:
            return self.clob_client.get_orders(self.address, include_filled=False)
        except Exception as e:
            bot_logger.error(f"Error getting positions: {e}")
            return []
    
    async def get_balance(self) -> Decimal:
        """Get account balance in USDC"""
        try:
            # Get USDC balance on Polygon
            usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon
            usdc_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }
            ]
            
            usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(usdc_address),
                abi=usdc_abi
            )
            
            balance_wei = usdc_contract.functions.balanceOf(self.address).call()
            balance = Decimal(balance_wei) / Decimal(10**6)  # USDC has 6 decimals
            
            bot_logger.info(f"Account balance: {balance} USDC")
            return balance
            
        except Exception as e:
            bot_logger.error(f"Error getting balance: {e}")
            return Decimal(0)
    
    async def monitor_market_resolution(self, market_id: str) -> Optional[str]:
        """
        Monitor market for resolution
        
        Args:
            market_id: Market to monitor
        
        Returns:
            Resolution outcome if resolved, None otherwise
        """
        try:
            # Query for market resolution
            query = gql("""
                query GetMarketResolution($id: ID!) {
                    market(id: $id) {
                        resolved
                        resolvedOutcome
                    }
                }
            """)
            
            variables = {"id": market_id}
            result = await self.gql_client.execute_async(query, variable_values=variables)
            
            market = result.get("market", {})
            if market.get("resolved"):
                return market.get("resolvedOutcome")
            
            return None
            
        except Exception as e:
            bot_logger.error(f"Error checking market resolution: {e}")
            return None
