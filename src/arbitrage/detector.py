"""
Arbitrage detection engine for identifying profitable opportunities
"""
import asyncio
import uuid
from typing import List, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import numpy as np
from scipy import stats

from src.models import (
    PolymarketMarket,
    SpotMarket,
    ArbitrageOpportunity,
    ArbitrageType,
    MarketSide
)
from src.exchanges.polymarket_client import PolymarketClient
from src.exchanges.cex_client import ExchangeClient
from src.config import config
from src.utils.logger import bot_logger


class ArbitrageDetector:
    """Detects arbitrage opportunities between Polymarket and CEX"""
    
    def __init__(
        self,
        polymarket_client: PolymarketClient,
        exchange_client: ExchangeClient
    ):
        """
        Initialize arbitrage detector
        
        Args:
            polymarket_client: Polymarket client instance
            exchange_client: Exchange client instance
        """
        self.polymarket = polymarket_client
        self.exchange = exchange_client
        
        # Detection parameters
        self.min_profit_threshold = config.MIN_PROFIT_THRESHOLD_USD
        self.max_position_size = config.MAX_POSITION_SIZE_USD
        self.slippage_buffer = config.slippage_decimal
        
        # Cached market data
        self.last_opportunities: List[ArbitrageOpportunity] = []
        
        bot_logger.info("Initialized arbitrage detector")
    
    async def scan_for_opportunities(
        self,
        assets: List[str] = ["BTC", "ETH"]
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for arbitrage opportunities across assets
        
        Args:
            assets: List of assets to scan
        
        Returns:
            List of detected opportunities
        """
        opportunities = []
        
        for asset in assets:
            try:
                # Get Polymarket markets
                polymarkets = await self.polymarket.get_markets_by_asset(asset)
                
                if not polymarkets:
                    bot_logger.debug(f"No active Polymarket markets for {asset}")
                    continue
                
                # Get spot/futures price
                spot_market = await self.exchange.get_market_data(asset, use_futures=True)
                
                if not spot_market:
                    bot_logger.error(f"Could not fetch market data for {asset}")
                    continue
                
                # Check each Polymarket for opportunities
                for pm_market in polymarkets:
                    opportunity = await self._analyze_market_pair(pm_market, spot_market)
                    if opportunity:
                        opportunities.append(opportunity)
                
            except Exception as e:
                bot_logger.error(f"Error scanning {asset}: {e}")
        
        # Sort by expected profit
        opportunities.sort(key=lambda x: x.expected_profit_usd, reverse=True)
        
        self.last_opportunities = opportunities
        
        bot_logger.info(f"Found {len(opportunities)} arbitrage opportunities")
        return opportunities
    
    async def _analyze_market_pair(
        self,
        pm_market: PolymarketMarket,
        spot_market: SpotMarket
    ) -> Optional[ArbitrageOpportunity]:
        """
        Analyze a specific Polymarket vs spot market pair
        
        Args:
            pm_market: Polymarket market data
            spot_market: Spot/futures market data
        
        Returns:
            ArbitrageOpportunity if profitable, None otherwise
        """
        try:
            # Calculate probabilities and expected values
            current_price = spot_market.mid_price
            target_price = pm_market.target_price
            hours_to_expiry = pm_market.time_to_expiry_hours
            
            if hours_to_expiry <= 0:
                return None  # Market expired
            
            # Calculate price distance as percentage
            price_distance_pct = abs(current_price - target_price) / current_price * 100
            
            # Determine which side to take on Polymarket
            if current_price < target_price:
                # Current price below target - bet on "Down"
                pm_side = MarketSide.DOWN
                pm_price = pm_market.down_price
                hedge_side = MarketSide.LONG  # Go long to hedge
                
                # We profit if price stays below target
                breakeven_price = target_price
                
            else:
                # Current price above target - bet on "Up"
                pm_side = MarketSide.UP
                pm_price = pm_market.up_price
                hedge_side = MarketSide.SHORT  # Go short to hedge
                
                # We profit if price stays above target
                breakeven_price = target_price
            
            # Skip if Polymarket price is too high (low profit potential)
            if pm_price > Decimal("0.85"):
                return None
            
            # Calculate position sizes
            pm_position_value = min(
                self.max_position_size * Decimal("0.5"),  # Use half capital for PM
                pm_market.up_liquidity if pm_side == MarketSide.UP else pm_market.down_liquidity
            )
            pm_quantity = pm_position_value / pm_price
            
            # Calculate hedge size (delta neutral)
            # If PM position wins, we get pm_quantity shares worth $1 each
            # So we need to hedge pm_quantity * (1 - pm_price) worth
            hedge_value = pm_quantity * (1 - pm_price)
            hedge_quantity = hedge_value / current_price
            
            # Calculate expected profit
            # Scenario 1: Polymarket wins (price stays on our side of target)
            pm_profit = pm_quantity * (1 - pm_price)  # Profit from PM
            
            # Calculate hedge loss/profit at target
            if hedge_side == MarketSide.LONG:
                hedge_pnl_at_target = hedge_quantity * (target_price - current_price)
            else:
                hedge_pnl_at_target = hedge_quantity * (current_price - target_price)
            
            # Expected profit if we win (simplified - assuming we exit hedge at target)
            win_profit = pm_profit - abs(hedge_pnl_at_target) * Decimal("0.5")  # Assume we can exit hedge midway
            
            # Scenario 2: Polymarket loses
            pm_loss = pm_quantity * pm_price  # Loss from PM
            
            # Maximum risk
            max_risk = pm_position_value  # Maximum we can lose on PM
            
            # Calculate probability of profit using volatility
            prob_profit = self._calculate_probability_of_profit(
                current_price,
                target_price,
                hours_to_expiry,
                pm_side
            )
            
            # Expected value
            expected_profit = (prob_profit * win_profit) - ((1 - prob_profit) * pm_loss)
            
            # Apply fees
            total_fees = (
                pm_position_value * Decimal("0.002") +  # Polymarket fees
                hedge_value * self.exchange.taker_fee * 2  # Entry and exit fees
            )
            
            expected_profit -= total_fees
            
            # Check if profitable
            if expected_profit < self.min_profit_threshold:
                return None
            
            # Calculate profit percentage
            total_capital = pm_position_value + hedge_value
            profit_percentage = (expected_profit / total_capital) * 100
            
            # Create opportunity
            opportunity = ArbitrageOpportunity(
                opportunity_id=str(uuid.uuid4()),
                type=ArbitrageType.FUTURES_HEDGE if self.exchange.has_futures else ArbitrageType.SPOT_HEDGE,
                polymarket=pm_market,
                spot_market=spot_market,
                polymarket_side=pm_side,
                polymarket_price=pm_price,
                polymarket_quantity=pm_quantity,
                hedge_side=hedge_side,
                hedge_price=current_price,
                hedge_quantity=hedge_quantity,
                expected_profit_usd=expected_profit,
                expected_profit_percentage=profit_percentage,
                breakeven_price=breakeven_price,
                max_risk_usd=max_risk,
                probability_of_profit=prob_profit,
                expires_at=pm_market.expiry_time
            )
            
            # Calculate Sharpe ratio
            opportunity.sharpe_ratio = self._calculate_sharpe_ratio(
                expected_profit,
                max_risk,
                hours_to_expiry
            )
            
            bot_logger.info(
                f"Found opportunity: {pm_market.asset} {pm_side.value} "
                f"Expected profit: ${expected_profit:.2f} ({profit_percentage:.1f}%) "
                f"Probability: {prob_profit:.1%}"
            )
            
            return opportunity
            
        except Exception as e:
            bot_logger.error(f"Error analyzing market pair: {e}")
            return None
    
    def _calculate_probability_of_profit(
        self,
        current_price: Decimal,
        target_price: Decimal,
        hours_to_expiry: float,
        side: MarketSide
    ) -> Decimal:
        """
        Calculate probability of profit using Black-Scholes-like model
        
        Args:
            current_price: Current spot price
            target_price: Polymarket target price
            hours_to_expiry: Time until expiry in hours
            side: Which side we're taking
        
        Returns:
            Probability between 0 and 1
        """
        try:
            # Estimate volatility (simplified - should use historical data)
            # BTC/ETH typically have ~2-4% daily volatility
            daily_volatility = Decimal("0.03")  # 3% daily
            hourly_volatility = daily_volatility / Decimal(24).sqrt()
            
            # Calculate standard deviation for the period
            time_in_days = Decimal(str(hours_to_expiry)) / 24
            period_std = daily_volatility * time_in_days.sqrt()
            
            # Calculate z-score
            price_return = (target_price - current_price) / current_price
            z_score = float(price_return / period_std)
            
            # Calculate probability using normal distribution
            if side == MarketSide.DOWN:
                # Probability that price stays below target
                probability = Decimal(str(stats.norm.cdf(z_score)))
            else:
                # Probability that price stays above target
                probability = Decimal(str(1 - stats.norm.cdf(z_score)))
            
            # Apply small adjustment based on time decay
            # Markets tend to be range-bound more often than expected
            time_adjustment = min(Decimal("0.1"), Decimal(str(hours_to_expiry)) / 240)
            probability = probability * (1 + time_adjustment)
            
            # Clamp between 0 and 1
            return max(Decimal(0), min(Decimal(1), probability))
            
        except Exception as e:
            bot_logger.error(f"Error calculating probability: {e}")
            # Return conservative estimate
            return Decimal("0.4")
    
    def _calculate_sharpe_ratio(
        self,
        expected_profit: Decimal,
        max_risk: Decimal,
        hours_to_expiry: float
    ) -> Decimal:
        """
        Calculate Sharpe ratio for the opportunity
        
        Args:
            expected_profit: Expected profit
            max_risk: Maximum risk
            hours_to_expiry: Time until expiry
        
        Returns:
            Sharpe ratio
        """
        try:
            if max_risk == 0:
                return Decimal(0)
            
            # Annualize the return
            periods_per_year = Decimal(365 * 24) / Decimal(str(max(1, hours_to_expiry)))
            annualized_return = expected_profit * periods_per_year
            
            # Use max risk as proxy for standard deviation
            annualized_std = max_risk * periods_per_year.sqrt()
            
            # Risk-free rate (assume 5% annually)
            risk_free_rate = Decimal("0.05")
            
            # Calculate Sharpe ratio
            sharpe = (annualized_return - risk_free_rate) / annualized_std
            
            return sharpe
            
        except Exception as e:
            bot_logger.error(f"Error calculating Sharpe ratio: {e}")
            return Decimal(0)
    
    async def validate_opportunity(
        self,
        opportunity: ArbitrageOpportunity
    ) -> Tuple[bool, List[str]]:
        """
        Validate an opportunity before execution
        
        Args:
            opportunity: Opportunity to validate
        
        Returns:
            Tuple of (is_valid, list_of_warnings)
        """
        warnings = []
        
        try:
            # Check if market is still active
            if opportunity.expires_at <= datetime.utcnow():
                return False, ["Market has expired"]
            
            # Re-fetch current prices
            current_spot = await self.exchange.get_market_data(
                opportunity.polymarket.asset,
                use_futures=True
            )
            
            if not current_spot:
                return False, ["Cannot fetch current market data"]
            
            # Check price movement
            price_change = abs(current_spot.mid_price - opportunity.hedge_price)
            price_change_pct = (price_change / opportunity.hedge_price) * 100
            
            if price_change_pct > 2:
                warnings.append(f"Price has moved {price_change_pct:.1f}% since detection")
            
            # Check liquidity on Polymarket
            pm_book = await self.polymarket.get_order_book(
                opportunity.polymarket.market_id,
                opportunity.polymarket_side.value
            )
            
            if opportunity.polymarket_side == MarketSide.UP:
                available_liquidity = sum(ask.quantity for ask in pm_book["asks"])
            else:
                available_liquidity = sum(bid.quantity for bid in pm_book["bids"])
            
            if available_liquidity < opportunity.polymarket_quantity:
                warnings.append(f"Insufficient Polymarket liquidity: {available_liquidity:.0f} available")
            
            # Check account balances
            pm_balance = await self.polymarket.get_balance()
            exchange_balances = await self.exchange.get_balance()
            usdt_balance = exchange_balances.get("USDT", Decimal(0))
            
            required_pm_capital = opportunity.polymarket_quantity * opportunity.polymarket_price
            required_hedge_capital = opportunity.hedge_quantity * opportunity.hedge_price
            
            if pm_balance < required_pm_capital:
                return False, [f"Insufficient Polymarket balance: ${pm_balance:.2f}"]
            
            if usdt_balance < required_hedge_capital:
                return False, [f"Insufficient exchange balance: ${usdt_balance:.2f}"]
            
            # All checks passed
            is_valid = len(warnings) == 0 or (
                len(warnings) == 1 and "Price has moved" in warnings[0]
            )
            
            return is_valid, warnings
            
        except Exception as e:
            bot_logger.error(f"Error validating opportunity: {e}")
            return False, [str(e)]
