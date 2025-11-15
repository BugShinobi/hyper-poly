"""
Enhanced arbitrage detector for Polymarket vs Hyperliquid
"""
import asyncio
import uuid
from typing import List, Optional, Tuple, Dict
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
from src.exchanges.hyperliquid_client import HyperliquidClient
from src.config import config
from src.utils.logger import bot_logger


class HyperliquidArbitrageDetector:
    """Detects arbitrage opportunities between Polymarket and Hyperliquid"""
    
    def __init__(
        self,
        polymarket_client: PolymarketClient,
        hyperliquid_client: HyperliquidClient
    ):
        """
        Initialize arbitrage detector
        
        Args:
            polymarket_client: Polymarket client instance
            hyperliquid_client: Hyperliquid client instance
        """
        self.polymarket = polymarket_client
        self.hyperliquid = hyperliquid_client
        
        # Detection parameters
        self.min_profit_threshold = config.MIN_PROFIT_THRESHOLD_USD
        self.max_position_size = config.MAX_POSITION_SIZE_USD
        self.slippage_buffer = config.slippage_decimal
        self.funding_threshold = config.FUNDING_RATE_THRESHOLD
        
        # Cache for market data and calculations
        self.last_opportunities: List[ArbitrageOpportunity] = []
        self.volatility_cache: Dict[str, Decimal] = {}
        
        bot_logger.info("Initialized Hyperliquid arbitrage detector")
    
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
                
                # Get Hyperliquid market data
                hl_market = await self.hyperliquid.get_market_data(asset)
                
                if not hl_market:
                    bot_logger.error(f"Could not fetch Hyperliquid data for {asset}")
                    continue
                
                # Get funding rate
                funding_rate = await self.hyperliquid.get_funding_rate(asset)
                
                # Check each Polymarket for opportunities
                for pm_market in polymarkets:
                    opportunity = await self._analyze_market_pair(
                        pm_market,
                        hl_market,
                        funding_rate
                    )
                    if opportunity:
                        opportunities.append(opportunity)
                
            except Exception as e:
                bot_logger.error(f"Error scanning {asset}: {e}")
        
        # Sort by expected profit adjusted for risk
        opportunities.sort(
            key=lambda x: x.expected_profit_usd * x.probability_of_profit,
            reverse=True
        )
        
        self.last_opportunities = opportunities
        
        bot_logger.info(f"Found {len(opportunities)} arbitrage opportunities")
        return opportunities
    
    async def _analyze_market_pair(
        self,
        pm_market: PolymarketMarket,
        hl_market: SpotMarket,
        funding_rate: Decimal
    ) -> Optional[ArbitrageOpportunity]:
        """
        Analyze a specific Polymarket vs Hyperliquid pair
        
        Args:
            pm_market: Polymarket market data
            hl_market: Hyperliquid market data
            funding_rate: Current funding rate
        
        Returns:
            ArbitrageOpportunity if profitable
        """
        try:
            current_price = hl_market.mid_price
            target_price = pm_market.target_price
            hours_to_expiry = pm_market.time_to_expiry_hours
            
            if hours_to_expiry <= 0:
                return None
            
            # Calculate funding cost/income
            funding_periods = int(hours_to_expiry / 8)  # Funding every 8 hours
            funding_cost_pct = funding_rate * funding_periods
            
            # Skip if funding is too negative (we'd be paying too much)
            if funding_cost_pct < -self.funding_threshold:
                bot_logger.debug(f"Skipping due to high funding cost: {funding_cost_pct:.4%}")
                return None
            
            # Determine optimal strategy
            strategy = self._determine_strategy(
                current_price,
                target_price,
                pm_market,
                funding_rate
            )
            
            if not strategy:
                return None
            
            pm_side, hedge_side = strategy
            pm_price = pm_market.up_price if pm_side == MarketSide.UP else pm_market.down_price
            
            # Skip if Polymarket probability is too high
            if pm_price > Decimal("0.90"):
                return None
            
            # Calculate optimal position sizes
            positions = self._calculate_position_sizes(
                pm_market,
                hl_market,
                pm_side,
                pm_price,
                funding_cost_pct
            )
            
            if not positions:
                return None
            
            pm_quantity, hedge_quantity = positions
            
            # Calculate expected profit with funding
            profit_calc = self._calculate_expected_profit(
                pm_quantity,
                pm_price,
                hedge_quantity,
                current_price,
                target_price,
                hedge_side,
                funding_cost_pct,
                hours_to_expiry
            )
            
            if not profit_calc:
                return None
            
            expected_profit, max_risk, breakeven_price = profit_calc
            
            # Apply fees
            total_fees = self._calculate_total_fees(
                pm_quantity * pm_price,
                hedge_quantity * current_price
            )
            
            expected_profit -= total_fees
            
            # Check profitability
            if expected_profit < self.min_profit_threshold:
                return None
            
            # Calculate probability of profit
            prob_profit = self._calculate_probability_with_funding(
                current_price,
                target_price,
                hours_to_expiry,
                pm_side,
                funding_rate
            )
            
            # Calculate risk metrics
            total_capital = (pm_quantity * pm_price) + (hedge_quantity * current_price / config.DEFAULT_LEVERAGE)
            profit_percentage = (expected_profit / total_capital) * 100
            
            # Create opportunity
            opportunity = ArbitrageOpportunity(
                opportunity_id=str(uuid.uuid4()),
                type=ArbitrageType.FUTURES_HEDGE,
                polymarket=pm_market,
                spot_market=hl_market,
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
            opportunity.sharpe_ratio = self._calculate_sharpe_with_funding(
                expected_profit,
                max_risk,
                hours_to_expiry,
                funding_rate
            )
            
            bot_logger.info(
                f"Found opportunity: {pm_market.asset} {pm_side.value} "
                f"Expected profit: ${expected_profit:.2f} ({profit_percentage:.1f}%) "
                f"Probability: {prob_profit:.1%} "
                f"Funding: {funding_cost_pct:.4%}"
            )
            
            return opportunity
            
        except Exception as e:
            bot_logger.error(f"Error analyzing market pair: {e}")
            return None
    
    def _determine_strategy(
        self,
        current_price: Decimal,
        target_price: Decimal,
        pm_market: PolymarketMarket,
        funding_rate: Decimal
    ) -> Optional[Tuple[MarketSide, MarketSide]]:
        """
        Determine optimal strategy based on market conditions
        
        Returns:
            Tuple of (polymarket_side, hedge_side) or None
        """
        price_diff_pct = (current_price - target_price) / target_price * 100
        
        # If funding is positive (longs pay shorts), prefer short hedge
        funding_bias = funding_rate > 0
        
        if abs(price_diff_pct) < 1:
            # Price too close to target, risky
            return None
        
        if current_price < target_price:
            # Current below target
            if funding_bias:
                # Positive funding favors being short
                # But we need to hedge DOWN bet with LONG
                # Check if profit outweighs funding cost
                if pm_market.down_price < Decimal("0.6"):
                    return (MarketSide.DOWN, MarketSide.LONG)
            else:
                # Negative funding favors being long
                return (MarketSide.DOWN, MarketSide.LONG)
        else:
            # Current above target
            if funding_bias:
                # Positive funding favors being short - good for us
                return (MarketSide.UP, MarketSide.SHORT)
            else:
                # Negative funding makes short expensive
                if pm_market.up_price < Decimal("0.6"):
                    return (MarketSide.UP, MarketSide.SHORT)
        
        return None
    
    def _calculate_position_sizes(
        self,
        pm_market: PolymarketMarket,
        hl_market: SpotMarket,
        pm_side: MarketSide,
        pm_price: Decimal,
        funding_cost_pct: Decimal
    ) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Calculate optimal position sizes considering liquidity and risk
        
        Returns:
            Tuple of (polymarket_quantity, hedge_quantity) or None
        """
        try:
            # Check available liquidity
            pm_liquidity = pm_market.up_liquidity if pm_side == MarketSide.UP else pm_market.down_liquidity
            
            # Calculate maximum position based on liquidity and capital
            max_pm_value = min(
                self.max_position_size * Decimal("0.4"),  # Use 40% for Polymarket
                pm_liquidity * Decimal("0.1")  # Take max 10% of liquidity
            )
            
            pm_quantity = max_pm_value / pm_price
            
            # Calculate hedge size for delta neutrality
            # Account for leverage on Hyperliquid
            leverage = config.DEFAULT_LEVERAGE
            
            # Adjust for funding cost
            funding_adjustment = 1 + funding_cost_pct
            hedge_value = pm_quantity * (1 - pm_price) * funding_adjustment
            
            # With leverage, we need less capital
            hedge_capital_required = hedge_value / leverage
            
            # Check if we have enough capital
            if hedge_capital_required > self.max_position_size * Decimal("0.6"):
                # Scale down positions
                scale_factor = (self.max_position_size * Decimal("0.6")) / hedge_capital_required
                pm_quantity *= scale_factor
                hedge_value *= scale_factor
            
            hedge_quantity = hedge_value / hl_market.mid_price
            
            return (pm_quantity, hedge_quantity)
            
        except Exception as e:
            bot_logger.error(f"Error calculating position sizes: {e}")
            return None
    
    def _calculate_expected_profit(
        self,
        pm_quantity: Decimal,
        pm_price: Decimal,
        hedge_quantity: Decimal,
        current_price: Decimal,
        target_price: Decimal,
        hedge_side: MarketSide,
        funding_cost_pct: Decimal,
        hours_to_expiry: float
    ) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
        """
        Calculate expected profit including funding
        
        Returns:
            Tuple of (expected_profit, max_risk, breakeven_price) or None
        """
        try:
            # Scenario 1: Polymarket wins
            pm_win_profit = pm_quantity * (1 - pm_price)
            
            # Calculate hedge P&L at target
            if hedge_side == MarketSide.LONG:
                hedge_pnl_at_target = hedge_quantity * (target_price - current_price)
            else:
                hedge_pnl_at_target = hedge_quantity * (current_price - target_price)
            
            # Account for funding
            funding_cost = hedge_quantity * current_price * abs(funding_cost_pct)
            
            # If we're SHORT and funding is positive, we earn funding
            if hedge_side == MarketSide.SHORT and funding_cost_pct > 0:
                funding_cost = -funding_cost  # It's income
            
            # Expected profit if Polymarket wins
            win_profit = pm_win_profit + hedge_pnl_at_target - funding_cost
            
            # Scenario 2: Polymarket loses
            pm_loss = pm_quantity * pm_price
            
            # Maximum risk
            max_risk = pm_quantity * pm_price + funding_cost
            
            # Calculate breakeven price
            if hedge_side == MarketSide.LONG:
                # For long hedge, we need price to go up enough to cover PM loss
                breakeven_price = current_price + (pm_loss / hedge_quantity)
            else:
                # For short hedge, we need price to go down enough
                breakeven_price = current_price - (pm_loss / hedge_quantity)
            
            # Probability weighted expected value
            prob = self._estimate_win_probability(current_price, target_price, hours_to_expiry, hedge_side)
            expected_profit = (prob * win_profit) - ((1 - prob) * pm_loss)
            
            return (expected_profit, max_risk, breakeven_price)
            
        except Exception as e:
            bot_logger.error(f"Error calculating expected profit: {e}")
            return None
    
    def _calculate_total_fees(
        self,
        pm_value: Decimal,
        hedge_value: Decimal
    ) -> Decimal:
        """Calculate total fees for the trade"""
        # Polymarket fees (approximately 0.2%)
        pm_fees = pm_value * Decimal("0.002")
        
        # Hyperliquid fees (taker fee for entry and exit)
        hl_fees = hedge_value * config.hyperliquid_fees["taker"] * 2
        
        return pm_fees + hl_fees
    
    def _calculate_probability_with_funding(
        self,
        current_price: Decimal,
        target_price: Decimal,
        hours_to_expiry: float,
        side: MarketSide,
        funding_rate: Decimal
    ) -> Decimal:
        """
        Calculate probability of profit including funding rate impact
        """
        try:
            # Get or calculate volatility
            volatility = self._get_implied_volatility(current_price, hours_to_expiry)
            
            # Adjust for funding rate bias
            # Positive funding creates downward pressure (shorts earn)
            # Negative funding creates upward pressure (longs earn)
            drift = -funding_rate * 8 * 365  # Annualized drift from funding
            
            # Calculate expected price with drift
            time_years = hours_to_expiry / (24 * 365)
            expected_return = drift * time_years
            
            # Adjust target for expected drift
            adjusted_target = target_price / (1 + expected_return)
            
            # Calculate z-score with adjusted target
            price_return = (adjusted_target - current_price) / current_price
            std_dev = volatility * np.sqrt(time_years)
            z_score = price_return / std_dev
            
            # Calculate probability
            if side == MarketSide.DOWN:
                probability = Decimal(str(stats.norm.cdf(z_score)))
            else:
                probability = Decimal(str(1 - stats.norm.cdf(z_score)))
            
            # Adjust for time decay advantage
            time_bonus = min(Decimal("0.15"), Decimal(str(hours_to_expiry)) / 168)  # Max 15% bonus
            probability = probability * (1 + time_bonus)
            
            return max(Decimal(0), min(Decimal(1), probability))
            
        except Exception as e:
            bot_logger.error(f"Error calculating probability: {e}")
            return Decimal("0.4")
    
    def _get_implied_volatility(
        self,
        price: Decimal,
        hours: float
    ) -> float:
        """Get or estimate implied volatility"""
        # In production, this would fetch from options markets or calculate from historical data
        # For now, use approximations
        if price > 50000:  # BTC
            return 0.6  # 60% annual volatility
        elif price > 2000:  # ETH
            return 0.75  # 75% annual volatility
        else:
            return 0.9  # 90% for others
    
    def _estimate_win_probability(
        self,
        current: Decimal,
        target: Decimal,
        hours: float,
        side: MarketSide
    ) -> Decimal:
        """Simple probability estimation"""
        distance_pct = abs(current - target) / current
        time_factor = min(1, hours / 48)  # More time = higher probability
        
        base_prob = Decimal("0.5") + (distance_pct * time_factor)
        
        return min(Decimal("0.85"), base_prob)
    
    def _calculate_sharpe_with_funding(
        self,
        expected_profit: Decimal,
        max_risk: Decimal,
        hours: float,
        funding_rate: Decimal
    ) -> Decimal:
        """Calculate Sharpe ratio including funding considerations"""
        try:
            if max_risk == 0:
                return Decimal(0)
            
            # Annualize return
            periods_per_year = Decimal(365 * 24) / Decimal(str(max(1, hours)))
            annualized_return = expected_profit * periods_per_year
            
            # Adjust volatility for funding rate stability
            # Positive funding reduces volatility for shorts
            vol_adjustment = 1 - abs(funding_rate) * 10  # Reduce vol by up to 10%
            
            annualized_std = max_risk * periods_per_year.sqrt() * Decimal(str(vol_adjustment))
            
            # Risk-free rate
            risk_free = Decimal("0.05")
            
            sharpe = (annualized_return - risk_free) / annualized_std
            
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
            current_hl = await self.hyperliquid.get_market_data(
                opportunity.polymarket.asset
            )
            
            if not current_hl:
                return False, ["Cannot fetch current Hyperliquid data"]
            
            # Check price movement
            price_change_pct = abs(current_hl.mid_price - opportunity.hedge_price) / opportunity.hedge_price * 100
            
            if price_change_pct > 1:
                warnings.append(f"Price moved {price_change_pct:.1f}% since detection")
            
            # Check funding rate change
            current_funding = await self.hyperliquid.get_funding_rate(opportunity.polymarket.asset)
            
            if abs(current_funding) > self.funding_threshold:
                warnings.append(f"High funding rate: {current_funding:.4%}")
            
            # Check Polymarket liquidity
            pm_book = await self.polymarket.get_order_book(
                opportunity.polymarket.market_id,
                opportunity.polymarket_side.value
            )
            
            available_liquidity = sum(
                level.quantity for level in 
                (pm_book["asks"] if opportunity.polymarket_side == MarketSide.UP else pm_book["bids"])
            )
            
            if available_liquidity < opportunity.polymarket_quantity * Decimal("0.8"):
                warnings.append(f"Reduced Polymarket liquidity: {available_liquidity:.0f}")
            
            # Check Hyperliquid order book
            hl_book = await self.hyperliquid.get_order_book(
                opportunity.polymarket.asset
            )
            
            hl_liquidity = sum(
                level.quantity for level in
                (hl_book["asks"] if opportunity.hedge_side == MarketSide.LONG else hl_book["bids"])[:5]
            )
            
            if hl_liquidity < opportunity.hedge_quantity:
                warnings.append(f"Insufficient Hyperliquid liquidity: {hl_liquidity:.4f}")
            
            # Check account balances
            pm_balance = await self.polymarket.get_balance()
            hl_balance = await self.hyperliquid.get_balance()
            
            required_pm = opportunity.polymarket_quantity * opportunity.polymarket_price
            required_hl = opportunity.hedge_quantity * opportunity.hedge_price / config.DEFAULT_LEVERAGE
            
            if pm_balance < required_pm:
                return False, [f"Insufficient Polymarket balance: ${pm_balance:.2f}"]
            
            if hl_balance < required_hl:
                return False, [f"Insufficient Hyperliquid balance: ${hl_balance:.2f}"]
            
            # Check if we should still proceed
            critical_warnings = [w for w in warnings if "liquidity" in w.lower() or "funding" in w.lower()]
            is_valid = len(critical_warnings) == 0
            
            return is_valid, warnings
            
        except Exception as e:
            bot_logger.error(f"Error validating opportunity: {e}")
            return False, [str(e)]
