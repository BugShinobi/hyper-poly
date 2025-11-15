"""
Hyperliquid execution engine for managing arbitrage positions
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
from src.exchanges.hyperliquid_client import HyperliquidClient
from src.config import config
from src.utils.logger import bot_logger


class ExecutionStrategy(str, Enum):
    """Execution strategy types"""
    AGGRESSIVE = "AGGRESSIVE"  # Market orders, fast execution
    PASSIVE = "PASSIVE"  # Limit orders, better prices
    ADAPTIVE = "ADAPTIVE"  # Mix based on conditions
    TWAP = "TWAP"  # Time-weighted average price


class HyperliquidExecutor:
    """Handles trade execution between Polymarket and Hyperliquid"""
    
    def __init__(
        self,
        polymarket_client: PolymarketClient,
        hyperliquid_client: HyperliquidClient,
        strategy: ExecutionStrategy = ExecutionStrategy.ADAPTIVE
    ):
        """
        Initialize execution engine
        
        Args:
            polymarket_client: Polymarket client instance
            hyperliquid_client: Hyperliquid client instance
            strategy: Execution strategy to use
        """
        self.polymarket = polymarket_client
        self.hyperliquid = hyperliquid_client
        self.strategy = strategy
        
        # Position tracking
        self.active_positions: Dict[str, Position] = {}
        self.position_history: List[Position] = []
        
        # Risk limits
        self.max_concurrent = config.MAX_CONCURRENT_POSITIONS
        self.max_daily_trades = config.MAX_DAILY_TRADES
        self.daily_trade_count = 0
        self.last_trade_reset = datetime.utcnow().date()
        
        # Execution metrics
        self.execution_times: List[float] = []
        self.slippage_history: List[Decimal] = []
        
        bot_logger.info(f"Initialized Hyperliquid executor with {strategy} strategy")
    
    async def execute_opportunity(
        self,
        opportunity: ArbitrageOpportunity
    ) -> Optional[Position]:
        """
        Execute an arbitrage opportunity with smart order routing
        
        Args:
            opportunity: Opportunity to execute
        
        Returns:
            Position object if successful
        """
        start_time = datetime.utcnow()
        
        # Pre-execution checks
        if not await self._pre_execution_checks(opportunity):
            return None
        
        # Create position object
        position = Position(
            position_id=str(uuid.uuid4()),
            opportunity_id=opportunity.opportunity_id,
            polymarket_side=opportunity.polymarket_side,
            hedge_exchange="hyperliquid",
            hedge_symbol=f"{opportunity.polymarket.asset}-USD-PERP",
            hedge_side=opportunity.hedge_side,
            max_loss_usd=opportunity.max_risk_usd,
            expires_at=opportunity.expires_at
        )
        
        try:
            bot_logger.info(f"Executing opportunity {opportunity.opportunity_id[:8]}")
            
            # Determine execution strategy
            exec_plan = self._create_execution_plan(opportunity)
            
            # Execute based on strategy
            if self.strategy == ExecutionStrategy.TWAP:
                success = await self._execute_twap(opportunity, position, exec_plan)
            else:
                success = await self._execute_parallel(opportunity, position, exec_plan)
            
            if not success:
                await self._rollback_position(position)
                return None
            
            # Set risk parameters
            await self._set_risk_parameters(position, opportunity)
            
            # Update position status
            position.status = PositionStatus.OPEN
            
            # Store position
            self.active_positions[position.position_id] = position
            self.daily_trade_count += 1
            
            # Track execution metrics
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            self.execution_times.append(execution_time)
            
            # Calculate and log slippage
            slippage = self._calculate_slippage(position, opportunity)
            self.slippage_history.append(slippage)
            
            bot_logger.info(
                f"✅ Position opened {position.position_id[:8]} - "
                f"PM: {position.polymarket_quantity:.2f} @ {position.polymarket_entry_price:.4f}, "
                f"HL: {position.hedge_quantity:.4f} @ ${position.hedge_entry_price:.2f} "
                f"(Execution: {execution_time:.1f}s, Slippage: {slippage:.2%})",
                extra={"trade": True}
            )
            
            return position
            
        except Exception as e:
            bot_logger.error(f"Error executing opportunity: {e}")
            await self._rollback_position(position)
            return None
    
    async def _pre_execution_checks(self, opportunity: ArbitrageOpportunity) -> bool:
        """Perform pre-execution risk and sanity checks"""
        # Check risk limits
        if not self._check_risk_limits():
            bot_logger.warning("Risk limits exceeded")
            return False
        
        # Check market hours (24/7 for crypto but good to have)
        if not self._check_market_hours():
            bot_logger.warning("Outside trading hours")
            return False
        
        # Check funding rate
        funding_rate = await self.hyperliquid.get_funding_rate(opportunity.polymarket.asset)
        if abs(funding_rate) > config.FUNDING_RATE_THRESHOLD * 2:
            bot_logger.warning(f"Extreme funding rate: {funding_rate:.4%}")
            return False
        
        # Check position concentration
        existing_exposure = sum(
            p.hedge_quantity * p.hedge_entry_price 
            for p in self.active_positions.values()
            if p.hedge_symbol.startswith(opportunity.polymarket.asset)
        )
        
        if existing_exposure > config.MAX_POSITION_SIZE_USD * Decimal("2"):
            bot_logger.warning(f"Position concentration limit reached for {opportunity.polymarket.asset}")
            return False
        
        return True
    
    def _create_execution_plan(self, opportunity: ArbitrageOpportunity) -> Dict[str, Any]:
        """Create detailed execution plan based on market conditions"""
        plan = {
            "use_market_orders": False,
            "polymarket_chunks": 1,
            "hyperliquid_chunks": 1,
            "leverage": config.DEFAULT_LEVERAGE,
            "post_only": False,
            "time_limit": 60  # seconds
        }
        
        hours_to_expiry = (opportunity.expires_at - datetime.utcnow()).total_seconds() / 3600
        
        if self.strategy == ExecutionStrategy.AGGRESSIVE or hours_to_expiry < 2:
            plan["use_market_orders"] = True
            plan["time_limit"] = 30
        elif self.strategy == ExecutionStrategy.PASSIVE:
            plan["use_market_orders"] = False
            plan["post_only"] = True
            plan["time_limit"] = 120
        elif self.strategy == ExecutionStrategy.TWAP:
            # Split large orders into chunks
            if opportunity.polymarket_quantity * opportunity.polymarket_price > 1000:
                plan["polymarket_chunks"] = 3
            if opportunity.hedge_quantity * opportunity.hedge_price > 5000:
                plan["hyperliquid_chunks"] = 5
        else:  # ADAPTIVE
            # Adapt based on conditions
            if hours_to_expiry < 4:
                plan["use_market_orders"] = True
            elif opportunity.expected_profit_percentage > 5:
                plan["use_market_orders"] = True
                plan["leverage"] = min(config.MAX_LEVERAGE, config.DEFAULT_LEVERAGE + 2)
        
        return plan
    
    async def _execute_parallel(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        exec_plan: Dict[str, Any]
    ) -> bool:
        """Execute both legs in parallel"""
        try:
            # Set leverage on Hyperliquid first
            await self.hyperliquid.set_leverage(
                opportunity.polymarket.asset,
                exec_plan["leverage"]
            )
            
            # Create execution tasks
            pm_task = asyncio.create_task(
                self._execute_polymarket_leg(opportunity, position, exec_plan)
            )
            hl_task = asyncio.create_task(
                self._execute_hyperliquid_leg(opportunity, position, exec_plan)
            )
            
            # Wait with timeout
            done, pending = await asyncio.wait(
                [pm_task, hl_task],
                timeout=exec_plan["time_limit"],
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
            
            # Check results
            pm_success = pm_task.done() and await pm_task
            hl_success = hl_task.done() and await hl_task
            
            return pm_success and hl_success
            
        except Exception as e:
            bot_logger.error(f"Parallel execution failed: {e}")
            return False
    
    async def _execute_twap(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        exec_plan: Dict[str, Any]
    ) -> bool:
        """Execute using Time-Weighted Average Price strategy"""
        try:
            # Set leverage
            await self.hyperliquid.set_leverage(
                opportunity.polymarket.asset,
                exec_plan["leverage"]
            )
            
            # Calculate chunk sizes
            pm_chunk_size = opportunity.polymarket_quantity / exec_plan["polymarket_chunks"]
            hl_chunk_size = opportunity.hedge_quantity / exec_plan["hyperliquid_chunks"]
            
            # Execute in waves
            max_chunks = max(exec_plan["polymarket_chunks"], exec_plan["hyperliquid_chunks"])
            interval = exec_plan["time_limit"] / max_chunks
            
            pm_filled = Decimal(0)
            hl_filled = Decimal(0)
            
            for i in range(max_chunks):
                # Execute Polymarket chunk if needed
                if i < exec_plan["polymarket_chunks"]:
                    pm_order = await self.polymarket.place_order(
                        market_id=opportunity.polymarket.market_id,
                        side=opportunity.polymarket_side,
                        order_type=OrderType.LIMIT if not exec_plan["use_market_orders"] else OrderType.MARKET,
                        quantity=pm_chunk_size,
                        price=opportunity.polymarket_price * Decimal("1.01")  # Slightly aggressive
                    )
                    if pm_order:
                        pm_filled += pm_chunk_size
                
                # Execute Hyperliquid chunk if needed
                if i < exec_plan["hyperliquid_chunks"]:
                    hl_order = await self.hyperliquid.place_order(
                        asset=opportunity.polymarket.asset,
                        side=opportunity.hedge_side,
                        order_type=OrderType.LIMIT if not exec_plan["use_market_orders"] else OrderType.MARKET,
                        quantity=hl_chunk_size,
                        price=opportunity.hedge_price,
                        leverage=exec_plan["leverage"],
                        post_only=exec_plan["post_only"]
                    )
                    if hl_order:
                        hl_filled += hl_chunk_size
                
                # Wait before next chunk
                if i < max_chunks - 1:
                    await asyncio.sleep(interval)
            
            # Update position with actual fills
            position.polymarket_quantity = pm_filled
            position.hedge_quantity = hl_filled
            
            # Check if we got sufficient fills
            pm_fill_rate = pm_filled / opportunity.polymarket_quantity
            hl_fill_rate = hl_filled / opportunity.hedge_quantity
            
            return pm_fill_rate > 0.8 and hl_fill_rate > 0.8
            
        except Exception as e:
            bot_logger.error(f"TWAP execution failed: {e}")
            return False
    
    async def _execute_polymarket_leg(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        exec_plan: Dict[str, Any]
    ) -> bool:
        """Execute Polymarket leg"""
        try:
            order_type = OrderType.MARKET if exec_plan["use_market_orders"] else OrderType.LIMIT
            
            # Calculate order price
            if order_type == OrderType.LIMIT:
                # Place slightly aggressive limit order
                if opportunity.polymarket_side == MarketSide.UP:
                    price = opportunity.polymarket_price * Decimal("1.005")
                else:
                    price = opportunity.polymarket_price * Decimal("0.995")
            else:
                price = None
            
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
            
            # Wait for fill
            filled = await self._wait_for_fill(
                order_id,
                is_polymarket=True,
                timeout=exec_plan["time_limit"] // 2
            )
            
            if filled:
                order_status = await self.polymarket.get_order_status(order_id)
                position.polymarket_entry_price = Decimal(str(order_status.get("price", 0)))
                position.polymarket_quantity = Decimal(str(order_status.get("filled", 0)))
                position.polymarket_fees = Decimal(str(order_status.get("fees", 0)))
                return True
            
            await self.polymarket.cancel_order(order_id)
            return False
            
        except Exception as e:
            bot_logger.error(f"Polymarket execution failed: {e}")
            return False
    
    async def _execute_hyperliquid_leg(
        self,
        opportunity: ArbitrageOpportunity,
        position: Position,
        exec_plan: Dict[str, Any]
    ) -> bool:
        """Execute Hyperliquid leg"""
        try:
            order_type = OrderType.MARKET if exec_plan["use_market_orders"] else OrderType.LIMIT
            
            # Place order
            order_id = await self.hyperliquid.place_order(
                asset=opportunity.polymarket.asset,
                side=opportunity.hedge_side,
                order_type=order_type,
                quantity=opportunity.hedge_quantity,
                price=opportunity.hedge_price if order_type == OrderType.LIMIT else None,
                leverage=exec_plan["leverage"],
                post_only=exec_plan["post_only"]
            )
            
            if not order_id:
                return False
            
            position.hedge_order_id = order_id
            
            # For Hyperliquid, orders execute quickly
            await asyncio.sleep(0.5)
            
            # Get position info
            positions = await self.hyperliquid.get_positions()
            for pos in positions:
                if pos["coin"] == opportunity.polymarket.asset:
                    position.hedge_entry_price = pos["entry_price"]
                    position.hedge_quantity = abs(pos["size"])
                    position.hedge_fees = Decimal(str(config.hyperliquid_fees["taker"])) * position.hedge_quantity * position.hedge_entry_price
                    return True
            
            return False
            
        except Exception as e:
            bot_logger.error(f"Hyperliquid execution failed: {e}")
            return False
    
    async def _set_risk_parameters(
        self,
        position: Position,
        opportunity: ArbitrageOpportunity
    ):
        """Set stop loss and take profit levels"""
        try:
            # Calculate stop loss (tighter for Hyperliquid due to leverage)
            leverage = config.DEFAULT_LEVERAGE
            adjusted_stop_pct = config.stop_loss_decimal / leverage
            
            if position.hedge_side == MarketSide.LONG:
                position.stop_loss_price = position.hedge_entry_price * (1 - adjusted_stop_pct)
            else:
                position.stop_loss_price = position.hedge_entry_price * (1 + adjusted_stop_pct)
            
            # Calculate take profit (closer to breakeven for safety)
            position.take_profit_price = opportunity.breakeven_price * Decimal("0.95")
            
            # Note: Hyperliquid doesn't have native stop/take profit orders
            # These will be monitored and executed by our monitoring system
            
        except Exception as e:
            bot_logger.error(f"Error setting risk parameters: {e}")
    
    def _calculate_slippage(
        self,
        position: Position,
        opportunity: ArbitrageOpportunity
    ) -> Decimal:
        """Calculate execution slippage"""
        try:
            pm_slippage = abs(position.polymarket_entry_price - opportunity.polymarket_price) / opportunity.polymarket_price
            hl_slippage = abs(position.hedge_entry_price - opportunity.hedge_price) / opportunity.hedge_price
            
            return (pm_slippage + hl_slippage) / 2
            
        except:
            return Decimal(0)
    
    async def _wait_for_fill(
        self,
        order_id: str,
        is_polymarket: bool,
        timeout: int = 60
    ) -> bool:
        """Wait for order fill"""
        start = datetime.utcnow()
        
        while (datetime.utcnow() - start).total_seconds() < timeout:
            try:
                if is_polymarket:
                    status = await self.polymarket.get_order_status(order_id)
                    if status.get("filled", 0) > 0:
                        return True
                else:
                    # For Hyperliquid, check positions
                    return True  # Hyperliquid executes immediately
                
                await asyncio.sleep(1)
                
            except Exception as e:
                bot_logger.error(f"Error checking order status: {e}")
                await asyncio.sleep(1)
        
        return False
    
    async def _rollback_position(self, position: Position):
        """Rollback a partially executed position"""
        bot_logger.warning(f"Rolling back position {position.position_id[:8]}")
        
        try:
            # Close Polymarket position if exists
            if position.polymarket_quantity and position.polymarket_quantity > 0:
                # Place opposite order to close
                close_side = MarketSide.DOWN if position.polymarket_side == MarketSide.UP else MarketSide.UP
                await self.polymarket.place_order(
                    market_id=position.opportunity_id,  # Need proper market_id
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=position.polymarket_quantity
                )
            
            # Close Hyperliquid position if exists
            if position.hedge_quantity and position.hedge_quantity > 0:
                await self.hyperliquid.close_position(
                    position.hedge_symbol.split("-")[0]  # Extract asset
                )
            
            position.status = PositionStatus.CANCELLED
            
        except Exception as e:
            bot_logger.error(f"Rollback error: {e}")
            position.status = PositionStatus.ERROR
    
    def _check_risk_limits(self) -> bool:
        """Check if risk limits allow new trades"""
        # Reset daily counter
        if datetime.utcnow().date() > self.last_trade_reset:
            self.daily_trade_count = 0
            self.last_trade_reset = datetime.utcnow().date()
        
        if len(self.active_positions) >= self.max_concurrent:
            return False
        
        if self.daily_trade_count >= self.max_daily_trades:
            return False
        
        return True
    
    def _check_market_hours(self) -> bool:
        """Check if markets are open (always true for crypto)"""
        return True
    
    async def monitor_positions(self):
        """Monitor and manage active positions"""
        while True:
            try:
                for position_id, position in list(self.active_positions.items()):
                    if position.status != PositionStatus.OPEN:
                        continue
                    
                    # Check expiry
                    if datetime.utcnow() >= position.expires_at:
                        await self.close_position(position, reason="Market expired")
                        continue
                    
                    # Get current price
                    asset = position.hedge_symbol.split("-")[0]
                    market = await self.hyperliquid.get_market_data(asset)
                    
                    if not market:
                        continue
                    
                    current_price = market.mid_price
                    
                    # Calculate P&L
                    if position.hedge_side == MarketSide.LONG:
                        hedge_pnl = position.hedge_quantity * (current_price - position.hedge_entry_price)
                        
                        # Check stop/take profit
                        if current_price <= position.stop_loss_price:
                            await self.close_position(position, reason="Stop loss")
                        elif current_price >= position.take_profit_price:
                            await self.close_position(position, reason="Take profit")
                    else:
                        hedge_pnl = position.hedge_quantity * (position.hedge_entry_price - current_price)
                        
                        if current_price >= position.stop_loss_price:
                            await self.close_position(position, reason="Stop loss")
                        elif current_price <= position.take_profit_price:
                            await self.close_position(position, reason="Take profit")
                    
                    position.unrealized_pnl = hedge_pnl
                    
                    # Check funding
                    funding_rate = await self.hyperliquid.get_funding_rate(asset)
                    if abs(funding_rate) > config.FUNDING_RATE_THRESHOLD * 3:
                        bot_logger.warning(f"High funding rate {funding_rate:.4%} for {position_id[:8]}")
                        await self.close_position(position, reason="High funding rate")
                
                await asyncio.sleep(5)
                
            except Exception as e:
                bot_logger.error(f"Position monitoring error: {e}")
                await asyncio.sleep(10)
    
    async def close_position(self, position: Position, reason: str = "Manual"):
        """Close an active position"""
        try:
            bot_logger.info(f"Closing position {position.position_id[:8]} - {reason}")
            
            # Close Hyperliquid position
            if position.hedge_quantity > 0:
                asset = position.hedge_symbol.split("-")[0]
                await self.hyperliquid.close_position(asset)
            
            # Note: Polymarket positions typically settle at expiry
            
            # Update status
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.utcnow()
            
            # Move to history
            self.position_history.append(position)
            del self.active_positions[position.position_id]
            
            bot_logger.info(
                f"Closed {position.position_id[:8]} - P&L: ${position.net_pnl:.2f}",
                extra={"trade": True}
            )
            
        except Exception as e:
            bot_logger.error(f"Error closing position: {e}")
            position.status = PositionStatus.ERROR
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics"""
        if not self.execution_times:
            return {}
        
        return {
            "avg_execution_time": sum(self.execution_times) / len(self.execution_times),
            "avg_slippage": sum(self.slippage_history) / len(self.slippage_history) if self.slippage_history else 0,
            "total_positions": len(self.position_history),
            "active_positions": len(self.active_positions),
            "success_rate": len([p for p in self.position_history if p.net_pnl > 0]) / len(self.position_history) if self.position_history else 0
        }
