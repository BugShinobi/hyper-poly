"""
CEX client for spot and futures trading
"""
import asyncio
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
import ccxt.async_support as ccxt

from src.models import (
    SpotMarket,
    MarketSide,
    OrderType,
    PriceLevel
)
from src.config import config
from src.utils.logger import bot_logger


class ExchangeClient:
    """Client for interacting with centralized exchanges"""
    
    # Supported exchanges and their specifics
    EXCHANGE_CONFIG = {
        "binance": {
            "class": ccxt.binance,
            "futures_suffix": "USDT",
            "has_futures": True,
            "maker_fee": Decimal("0.0002"),  # 0.02%
            "taker_fee": Decimal("0.0004")   # 0.04%
        },
        "bybit": {
            "class": ccxt.bybit,
            "futures_suffix": "USDT",
            "has_futures": True,
            "maker_fee": Decimal("0.0001"),
            "taker_fee": Decimal("0.0006")
        },
        # "dydx": {  # Removed from CCXT
        #     "class": ccxt.dydx,
        #     "futures_suffix": "-USD",
        #     "has_futures": True,
        #     "maker_fee": Decimal("0"),
        #     "taker_fee": Decimal("0.0005")
        # },
        "okx": {
            "class": ccxt.okx,
            "futures_suffix": "-USDT-SWAP",
            "has_futures": True,
            "maker_fee": Decimal("0.0002"),
            "taker_fee": Decimal("0.0005")
        }
    }
    
    def __init__(self, exchange_name: Optional[str] = None):
        """
        Initialize exchange client
        
        Args:
            exchange_name: Name of exchange to use (defaults to config)
        """
        self.exchange_name = exchange_name or config.EXCHANGE_NAME.lower()
        
        if self.exchange_name not in self.EXCHANGE_CONFIG:
            raise ValueError(f"Unsupported exchange: {self.exchange_name}")
        
        exchange_config = self.EXCHANGE_CONFIG[self.exchange_name]
        ExchangeClass = exchange_config["class"]
        
        # Initialize exchange
        self.exchange = ExchangeClass({
            'apiKey': config.EXCHANGE_API_KEY,
            'secret': config.EXCHANGE_API_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future' if exchange_config["has_futures"] else 'spot'
            }
        })
        
        self.has_futures = exchange_config["has_futures"]
        self.futures_suffix = exchange_config["futures_suffix"]
        self.maker_fee = exchange_config["maker_fee"]
        self.taker_fee = exchange_config["taker_fee"]
        
        bot_logger.info(f"Initialized {self.exchange_name} client")
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def close(self):
        """Close exchange connection"""
        await self.exchange.close()
    
    def get_symbol(self, asset: str, use_futures: bool = True) -> str:
        """
        Get proper symbol for the exchange
        
        Args:
            asset: Base asset (BTC, ETH, etc.)
            use_futures: Whether to use futures symbol
        
        Returns:
            Formatted symbol for the exchange
        """
        if use_futures and self.has_futures:
            if self.exchange_name == "dydx":
                return f"{asset}{self.futures_suffix}"
            elif self.exchange_name == "okx":
                return f"{asset}{self.futures_suffix}"
            else:
                return f"{asset}/{self.futures_suffix}"
        else:
            return f"{asset}/USDT"
    
    async def get_market_data(self, asset: str, use_futures: bool = True) -> Optional[SpotMarket]:
        """
        Get current market data for an asset
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            use_futures: Whether to use futures market
        
        Returns:
            SpotMarket data
        """
        try:
            symbol = self.get_symbol(asset, use_futures)
            
            # Fetch ticker
            ticker = await self.exchange.fetch_ticker(symbol)
            
            # Fetch order book for better bid/ask
            order_book = await self.exchange.fetch_order_book(symbol, limit=5)
            
            return SpotMarket(
                exchange=self.exchange_name,
                symbol=symbol,
                bid=Decimal(str(order_book['bids'][0][0])) if order_book['bids'] else Decimal(str(ticker['bid'])),
                ask=Decimal(str(order_book['asks'][0][0])) if order_book['asks'] else Decimal(str(ticker['ask'])),
                last=Decimal(str(ticker['last'])),
                volume_24h=Decimal(str(ticker['quoteVolume']))
            )
            
        except Exception as e:
            bot_logger.error(f"Error fetching market data for {asset}: {e}")
            return None
    
    async def get_order_book(self, asset: str, use_futures: bool = True, limit: int = 20) -> Dict[str, List[PriceLevel]]:
        """
        Get order book for an asset
        
        Args:
            asset: Asset symbol
            use_futures: Whether to use futures market
            limit: Number of price levels to fetch
        
        Returns:
            Dictionary with 'bids' and 'asks' price levels
        """
        try:
            symbol = self.get_symbol(asset, use_futures)
            order_book = await self.exchange.fetch_order_book(symbol, limit=limit)
            
            bids = [
                PriceLevel(
                    price=Decimal(str(price)),
                    quantity=Decimal(str(quantity))
                )
                for price, quantity in order_book['bids']
            ]
            
            asks = [
                PriceLevel(
                    price=Decimal(str(price)),
                    quantity=Decimal(str(quantity))
                )
                for price, quantity in order_book['asks']
            ]
            
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
        use_futures: bool = True,
        reduce_only: bool = False
    ) -> Optional[str]:
        """
        Place an order on the exchange
        
        Args:
            asset: Asset to trade
            side: LONG or SHORT
            order_type: MARKET or LIMIT
            quantity: Order quantity
            price: Limit price (required for LIMIT orders)
            use_futures: Whether to use futures
            reduce_only: Whether this is a reduce-only order
        
        Returns:
            Order ID if successful
        """
        try:
            symbol = self.get_symbol(asset, use_futures)
            
            # Convert side
            order_side = 'buy' if side == MarketSide.LONG else 'sell'
            
            # Convert order type
            order_type_str = 'market' if order_type == OrderType.MARKET else 'limit'
            
            # Prepare parameters
            params = {}
            if use_futures and self.has_futures:
                params['reduceOnly'] = reduce_only
            
            # Place order
            if order_type == OrderType.MARKET:
                order = await self.exchange.create_order(
                    symbol=symbol,
                    type=order_type_str,
                    side=order_side,
                    amount=float(quantity),
                    params=params
                )
            else:
                if price is None:
                    raise ValueError("Price required for limit orders")
                
                order = await self.exchange.create_order(
                    symbol=symbol,
                    type=order_type_str,
                    side=order_side,
                    amount=float(quantity),
                    price=float(price),
                    params=params
                )
            
            order_id = order['id']
            bot_logger.info(
                f"Placed {order_side} order for {quantity} {asset} at "
                f"{price if price else 'market'} - Order ID: {order_id}",
                extra={"trade": True}
            )
            
            return order_id
            
        except Exception as e:
            bot_logger.error(f"Error placing order: {e}")
            return None
    
    async def get_order_status(self, order_id: str, asset: str, use_futures: bool = True) -> Dict[str, Any]:
        """Get status of a specific order"""
        try:
            symbol = self.get_symbol(asset, use_futures)
            order = await self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            bot_logger.error(f"Error getting order status: {e}")
            return {}
    
    async def cancel_order(self, order_id: str, asset: str, use_futures: bool = True) -> bool:
        """Cancel an open order"""
        try:
            symbol = self.get_symbol(asset, use_futures)
            result = await self.exchange.cancel_order(order_id, symbol)
            
            if result:
                bot_logger.info(f"Cancelled order: {order_id}")
                return True
            return False
            
        except Exception as e:
            bot_logger.error(f"Error cancelling order: {e}")
            return False
    
    async def get_positions(self, asset: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get open positions
        
        Args:
            asset: Filter by asset (None for all positions)
        
        Returns:
            List of position dictionaries
        """
        try:
            if not self.has_futures:
                bot_logger.warning("Exchange does not support futures positions")
                return []
            
            if asset:
                symbol = self.get_symbol(asset, use_futures=True)
                positions = await self.exchange.fetch_positions([symbol])
            else:
                positions = await self.exchange.fetch_positions()
            
            return positions
            
        except Exception as e:
            bot_logger.error(f"Error getting positions: {e}")
            return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """
        Get account balances
        
        Returns:
            Dictionary of asset -> balance
        """
        try:
            balance = await self.exchange.fetch_balance()
            
            # Extract free balances
            balances = {}
            for currency, details in balance['total'].items():
                if details > 0:
                    balances[currency] = Decimal(str(details))
            
            return balances
            
        except Exception as e:
            bot_logger.error(f"Error getting balance: {e}")
            return {}
    
    async def set_leverage(self, asset: str, leverage: int) -> bool:
        """
        Set leverage for futures trading
        
        Args:
            asset: Asset to set leverage for
            leverage: Leverage multiplier (1-125 depending on exchange)
        
        Returns:
            Success status
        """
        try:
            if not self.has_futures:
                bot_logger.warning("Exchange does not support futures")
                return False
            
            symbol = self.get_symbol(asset, use_futures=True)
            
            # Set leverage (method varies by exchange)
            if hasattr(self.exchange, 'set_leverage'):
                await self.exchange.set_leverage(leverage, symbol)
            else:
                # Some exchanges use different methods
                await self.exchange.private_post_position_leverage({
                    'symbol': symbol,
                    'leverage': leverage
                })
            
            bot_logger.info(f"Set leverage to {leverage}x for {symbol}")
            return True
            
        except Exception as e:
            bot_logger.error(f"Error setting leverage: {e}")
            return False
    
    def calculate_position_size(
        self,
        capital: Decimal,
        price: Decimal,
        leverage: int = 1
    ) -> Decimal:
        """
        Calculate position size based on capital and leverage
        
        Args:
            capital: Available capital in USDT
            price: Asset price
            leverage: Leverage to use
        
        Returns:
            Position size in asset units
        """
        # Account for fees
        effective_capital = capital * (1 - self.taker_fee)
        
        # Calculate with leverage
        position_value = effective_capital * leverage
        position_size = position_value / price
        
        return position_size
    
    def calculate_liquidation_price(
        self,
        entry_price: Decimal,
        side: MarketSide,
        leverage: int
    ) -> Decimal:
        """
        Calculate liquidation price for a leveraged position
        
        Args:
            entry_price: Entry price
            side: LONG or SHORT
            leverage: Position leverage
        
        Returns:
            Liquidation price
        """
        # Simplified calculation (actual varies by exchange)
        # Maintenance margin is typically 0.5% for most exchanges
        maintenance_margin = Decimal("0.005")
        
        if side == MarketSide.LONG:
            # Long liquidation: price drops by (100 - maintenance_margin) / leverage %
            liquidation_price = entry_price * (1 - (1 - maintenance_margin) / leverage)
        else:
            # Short liquidation: price rises by (100 - maintenance_margin) / leverage %
            liquidation_price = entry_price * (1 + (1 - maintenance_margin) / leverage)
        
        return liquidation_price
