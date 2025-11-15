"""
Trade execution engine for managing arbitrage positions
"""
import asyncio
import uuid
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum

from src.models import (
    ArbitrageOpportunity,
    Position,
    PositionStatus,
    MarketSide,
    OrderType,
    TradeSignal
)
from src.exchanges.polymarket_client import PolymarketClient
from src.exchanges.cex_client import ExchangeClient
from src.config import config
from src.utils.logger import bot_logger


class ExecutionStrategy(str, Enum):
    """Execution strategy types"""
    AGGRESSIVE = "AGGRESSIVE"  # Market orders, fast execution
    PASSIVE = "PASSIVE"  # Limit orders, better prices
    ADAPTIVE = "ADAPTIVE"  # Mix based on conditions


class ExecutionEngine:
    """Handles trade execution and position management"""
    
    def __init__(
        self,
        polymarket_client: PolymarketClient,
        exchange_client: ExchangeClient,
        strategy: ExecutionStrategy = ExecutionStrategy.ADAPTIVE
    ):
        """
        Initialize execution engine
        
        Args:
            polymarket_client: Polymarket client instance
            exchange_client: Exchange client instance
            strategy: Execution strategy to use
        """
        self.polymarket = polymarket_client
        self.exchange = exchange_client
        self.strategy = strategy
        
        # Position tracking
        self.active_positions: Dict[str, Position] = {}
        self.position_history: List[Position] = []
        
        # Risk limits
        self.max_concurrent = config.MAX_CONCURRENT_POSITIONS
        self.max_daily_trades = config.MAX_DAILY_TRADES
        self.daily_trade_count = 0
        self.last_trade_reset = datetime.utcnow().date()
        
        bot_logger.info(f"Initialized execution engine with {strategy} strategy")
    
    async def execute_opportunity(
        self,
        opportunity: ArbitrageOpportunity
    ) -> Optional[Position]:
        """
        Execute an arbitrage opportunity
        
        Args:
            opportunity: Opportunity to execute
        
        Returns:
            Position object if successful
        """
        # Check risk limits
        if not self._check_risk_limits():
            bot_logger.warning("Risk limits exceeded, skipping execution")
            return None
        
        # Create position object
        position = Position(
            position_id=str(uuid.uuid4()),
            opportunity_id=opportunity.opportunity_id,
            polymarket_side=opportunity.polymarket_side,
            hedge_exchange=self.exchange.exchange_name,
            hedge_symbol=self.exchange.get_symbol(opportunity.polymarket.asset),
            hedge_side=opportunity.hedge_side,
            max_loss_usd=opportunity.max_risk_usd,
            expires_at=opportunity.expires_at
        )
        
        try:
            # Execute both legs in parallel for speed
            bot_logger.info(f"Executing arbitrage opportunity {opportunity.opportunity_id}")
            
            # Determine execution strategy
            use_market_orders = self._should_use_market_orders(opportunity)
            
            # Execute trades
            pm_task = asyncio.create_task(
                self._execute_polymarket_leg(opportunity, position, use_market_orders)
            )
            hedge_task = asyncio.create_task(
                self._execute_hedge_leg(opportunity, position, use_market_orders)
            )
            
            # Wait for both to complete
            pm_success, hedge_success = await asyncio.gather(pm_task, hedge_task)
            
            if not pm_success or not hedge_success:
                # Rollback if either leg failed
                await self._rollback_position(position)
                return None
            
            # Calculate stop loss and take profit levels
            position.stop_loss_price = self._calculate_stop_loss(
                position.hedge_entry_price,
                position.hedge_side
            )
            position.take_profit_price = self._calculate_take_profit(
                position.hedge_entry_price,
                position.hedge_side,
                opportunity.breakeven_price
            )
            
            # Update position status
            position.status = PositionStatus.OPEN
            
            # Store position
            self.active_positions[position.position_id] = position
            self.daily_trade_count += 1
            
            bot_logger.info(
                f"Successfully opened position {position.position_id} - "
                f"PM: {position.polymarket_quantity:.2f} @ {position.polymarket_entry_price:.4f}, "
                f"Hedge: {position.hedge_quantity:.4f} @ {position.hedge_entry_price:.2f}",
                extra={"trade": True}
            )
            
            return position
            
        except Exception as e:
            bot_logger.error(f"Error executing opportunity: {e}")
            await self._rollback_position(position)
            return None
    
    def _should_use_market_orders(self, opportunity: ArbitrageOpportunity) -> bool:
        """Determine whether to use market orders based on strategy"""
        if self.strategy == ExecutionStrategy.AGGRESSIVE:
            return True
        elif self.strategy == ExecutionStrategy.PASSIVE:
            return False
        else:  # ADAPTIVE
            # Use market orders if time is running out or profit is very high
            hours_to_expiry = opportunity.time_value.total_seconds() / 3600
            
            if hours_to_expiry < 2:
                return True  # Use market orders close to expiry
            
            if opportunity.expected_profit_percentage > 5:
                return True  # High profit opportunity, execute quickly
            
            return False
    
    async def _execute_polymarket_leg(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        use_market_order: bool
    ) -> bool:
        """Execute the Polymarket leg of the trade"""
        try:
            # Determine order type and price
            if use_market_order:
                order_type = OrderType.MARKET
                price = None
            else:
                order_type = OrderType.LIMIT
                # Place limit order slightly better than current price
                if opportunity.polymarket_side == MarketSide.UP:
                    price = opportunity.polymarket_price * Decimal("0.99")
                else:
                    price = opportunity.polymarket_price * Decimal("1.01")
            
            # Place order
            order_id = await self.polymarket.place_order(
                market_id=opportunity.polymarket.market_id,
                side=opportunity.polymarket_side,
                order_type=order_type,
                quantity=opportunity.polymarket_quantity,
                price=price
            )
            
            if not order_id:
                return False
            
            position.polymarket_order_id = order_id
            
            # Wait for fill (with timeout)
            filled = await self._wait_for_fill(
                order_id,
                is_polymarket=True,
                timeout=30 if use_market_order else 60
            )
            
            if filled:
                # Update position with actual fill details
                order_status = await self.polymarket.get_order_status(order_id)
                position.polymarket_entry_price = Decimal(str(order_status.get("price", 0)))
                position.polymarket_quantity = Decimal(str(order_status.get("filled", 0)))
                position.polymarket_fees = Decimal(str(order_status.get("fees", 0)))
                return True
            
            # Cancel unfilled order
            await self.polymarket.cancel_order(order_id)
            return False
            
        except Exception as e:
            bot_logger.error(f"Error executing Polymarket leg: {e}")
            return False
    
    async def _execute_hedge_leg(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        use_market_order: bool
    ) -> bool:
        """Execute the hedge leg on the exchange"""
        try:
            # Set leverage if using futures
            if self.exchange.has_futures:
                await self.exchange.set_leverage(opportunity.polymarket.asset, 2)
            
            # Determine order type and price
            if use_market_order:
                order_type = OrderType.MARKET
                price = None
            else:
                order_type = OrderType.LIMIT
                # Place limit order at current price
                price = opportunity.hedge_price
            
            # Place order
            order_id = await self.exchange.place_order(
                asset=opportunity.polymarket.asset,
                side=opportunity.hedge_side,
                order_type=order_type,
                quantity=opportunity.hedge_quantity,
                price=price,
                use_futures=self.exchange.has_futures
            )
            
            if not order_id:
                return False
            
            position.hedge_order_id = order_id
            
            # Wait for fill
            filled = await self._wait_for_fill(
                order_id,
                is_polymarket=False,
                asset=opportunity.polymarket.asset,
                timeout=30 if use_market_order else 60
            )
            
            if filled:
                # Update position with actual fill details
                order_status = await self.exchange.get_order_status(
                    order_id,
                    opportunity.polymarket.asset,
                    use_futures=self.exchange.has_futures
                )
                position.hedge_entry_price = Decimal(str(order_status.get("price", 0)))
                position.hedge_quantity = Decimal(str(order_status.get("filled", 0)))
                position.hedge_fees = Decimal(str(order_status.get("fee", {}).get("cost", 0)))
                return True
            
            # Cancel unfilled order
            await self.exchange.cancel_order(
                order_id,
                opportunity.polymarket.asset,
                use_futures=self.exchange.has_futures
            )
            return False
            
        except Exception as e:
            bot_logger.error(f"Error executing hedge leg: {e}")
            return False
    
    async def _wait_for_fill(
        self,
        order_id: str,
        is_polymarket: bool,
        asset: Optional[str] = None,
        timeout: int = 60
    ) -> bool:
        """Wait for an order to be filled"""
        start_time = datetime.utcnow()
        
        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            try:
                if is_polymarket:
                    status = await self.polymarket.get_order_status(order_id)
                else:
                    status = await self.exchange.get_order_status(
                        order_id,
                        asset,
                        use_futures=self.exchange.has_futures
                    )
                
                if status.get("status") == "closed" or status.get("filled", 0) > 0:
                    return True
                
                await asyncio.sleep(1)
                
            except Exception as e:
                bot_logger.error(f"Error checking order status: {e}")
                await asyncio.sleep(1)
        
        return False
    
    async def _rollback_position(self, position: Position):
        """Rollback a partially executed position"""
        bot_logger.warning(f"Rolling back position {position.position_id}")
        
        try:
            # Cancel or close Polymarket position if exists
            if position.polymarket_order_id:
                if position.polymarket_entry_price:
                    # Position was filled, need to close it
                    await self.polymarket.place_order(
                        market_id=position.opportunity_id,  # This needs proper market_id
                        side=MarketSide.DOWN if position.polymarket_side == MarketSide.UP else MarketSide.UP,
                        order_type=OrderType.MARKET,
                        quantity=position.polymarket_quantity
                    )
                else:
                    # Just cancel the order
                    await self.polymarket.cancel_order(position.polymarket_order_id)
            
            # Cancel or close hedge position if exists
            if position.hedge_order_id:
                if position.hedge_entry_price:
                    # Position was filled, need to close it
                    close_side = MarketSide.SHORT if position.hedge_side == MarketSide.LONG else MarketSide.LONG
                    await self.exchange.place_order(
                        asset=position.hedge_symbol.split("/")[0],  # Extract asset from symbol
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=position.hedge_quantity,
                        use_futures=self.exchange.has_futures,
                        reduce_only=True
                    )
                else:
                    # Just cancel the order
                    await self.exchange.cancel_order(
                        position.hedge_order_id,
                        position.hedge_symbol.split("/")[0],
                        use_futures=self.exchange.has_futures
                    )
            
            position.status = PositionStatus.CANCELLED
            
        except Exception as e:
            bot_logger.error(f"Error during rollback: {e}")
            position.status = PositionStatus.ERROR
    
    def _calculate_stop_loss(
        self,
        entry_price: Decimal,
        side: MarketSide
    ) -> Decimal:
        """Calculate stop loss price"""
        stop_loss_pct = config.stop_loss_decimal
        
        if side == MarketSide.LONG:
            # For long positions, stop loss is below entry
            return entry_price * (1 - stop_loss_pct)
        else:
            # For short positions, stop loss is above entry
            return entry_price * (1 + stop_loss_pct)
    
    def _calculate_take_profit(
        self,
        entry_price: Decimal,
        side: MarketSide,
        target_price: Decimal
    ) -> Decimal:
        """Calculate take profit price"""
        # Set take profit halfway to the Polymarket target
        if side == MarketSide.LONG:
            # For long, take profit is above entry
            return entry_price + (target_price - entry_price) * Decimal("0.5")
        else:
            # For short, take profit is below entry
            return entry_price - (entry_price - target_price) * Decimal("0.5")
    
    def _check_risk_limits(self) -> bool:
        """Check if risk limits allow new trades"""
        # Reset daily counter if needed
        if datetime.utcnow().date() > self.last_trade_reset:
            self.daily_trade_count = 0
            self.last_trade_reset = datetime.utcnow().date()
        
        # Check concurrent positions
        if len(self.active_positions) >= self.max_concurrent:
            bot_logger.warning(f"Max concurrent positions reached: {len(self.active_positions)}")
            return False
        
        # Check daily trade limit
        if self.daily_trade_count >= self.max_daily_trades:
            bot_logger.warning(f"Max daily trades reached: {self.daily_trade_count}")
            return False
        
        return True
    
    async def monitor_positions(self):
        """Monitor and manage active positions"""
        while True:
            try:
                for position_id, position in list(self.active_positions.items()):
                    if position.status != PositionStatus.OPEN:
                        continue
                    
                    # Check if position expired
                    if datetime.utcnow() >= position.expires_at:
                        await self.close_position(position, reason="Market expired")
                        continue
                    
                    # Get current market price
                    asset = position.hedge_symbol.split("/")[0]
                    market_data = await self.exchange.get_market_data(asset)
                    
                    if not market_data:
                        continue
                    
                    current_price = market_data.mid_price
                    
                    # Calculate unrealized P&L
                    if position.hedge_side == MarketSide.LONG:
                        hedge_pnl = position.hedge_quantity * (current_price - position.hedge_entry_price)
                    else:
                        hedge_pnl = position.hedge_quantity * (position.hedge_entry_price - current_price)
                    
                    position.unrealized_pnl = hedge_pnl
                    
                    # Check stop loss
                    if position.hedge_side == MarketSide.LONG:
                        if current_price <= position.stop_loss_price:
                            await self.close_position(position, reason="Stop loss hit")
                    else:
                        if current_price >= position.stop_loss_price:
                            await self.close_position(position, reason="Stop loss hit")
                    
                    # Check take profit
                    if position.hedge_side == MarketSide.LONG:
                        if current_price >= position.take_profit_price:
                            await self.close_position(position, reason="Take profit hit")
                    else:
                        if current_price <= position.take_profit_price:
                            await self.close_position(position, reason="Take profit hit")
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                bot_logger.error(f"Error monitoring positions: {e}")
                await asyncio.sleep(10)
    
    async def close_position(self, position: Position, reason: str = "Manual"):
        """Close an active position"""
        try:
            bot_logger.info(f"Closing position {position.position_id} - Reason: {reason}")
            
            # Close hedge position
            if position.hedge_quantity > 0:
                asset = position.hedge_symbol.split("/")[0]
                close_side = MarketSide.SHORT if position.hedge_side == MarketSide.LONG else MarketSide.LONG
                
                await self.exchange.place_order(
                    asset=asset,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=position.hedge_quantity,
                    use_futures=self.exchange.has_futures,
                    reduce_only=True
                )
            
            # Note: Polymarket positions typically settle automatically at expiry
            # But we could implement early exit if needed
            
            # Update position status
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.utcnow()
            
            # Move to history
            self.position_history.append(position)
            del self.active_positions[position.position_id]
            
            bot_logger.info(
                f"Closed position {position.position_id} - Net P&L: ${position.net_pnl:.2f}",
                extra={"trade": True}
            )
            
        except Exception as e:
            bot_logger.error(f"Error closing position: {e}")
            position.status = PositionStatus.ERROR
