"""
Data models for the arbitrage bot
"""
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, validator
from dataclasses import dataclass


class MarketSide(str, Enum):
    """Market side for positions"""
    UP = "UP"
    DOWN = "DOWN"
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    """Order types"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class PositionStatus(str, Enum):
    """Position lifecycle status"""
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class ArbitrageType(str, Enum):
    """Type of arbitrage opportunity"""
    SPOT_HEDGE = "SPOT_HEDGE"
    FUTURES_HEDGE = "FUTURES_HEDGE"
    OPTIONS_HEDGE = "OPTIONS_HEDGE"


@dataclass
class PriceLevel:
    """Price level for order book data"""
    price: Decimal
    quantity: Decimal
    
    @property
    def value(self) -> Decimal:
        return self.price * self.quantity


class PolymarketMarket(BaseModel):
    """Polymarket market data"""
    market_id: str
    question: str
    asset: str  # BTC, ETH, etc.
    target_price: Decimal
    expiry_time: datetime
    up_price: Decimal = Field(ge=0, le=1)
    down_price: Decimal = Field(ge=0, le=1)
    up_liquidity: Decimal
    down_liquidity: Decimal
    volume_24h: Decimal
    open_interest: Decimal
    
    @validator("up_price", "down_price")
    def validate_prices(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("Polymarket prices must be between 0 and 1")
        return v
    
    @property
    def implied_probability_up(self) -> Decimal:
        """Calculate implied probability for UP outcome"""
        return self.up_price
    
    @property
    def implied_probability_down(self) -> Decimal:
        """Calculate implied probability for DOWN outcome"""
        return self.down_price
    
    @property
    def time_to_expiry_hours(self) -> float:
        """Calculate hours until market expiry"""
        delta = self.expiry_time - datetime.utcnow()
        return delta.total_seconds() / 3600


class SpotMarket(BaseModel):
    """Spot/Futures market data from CEX"""
    exchange: str
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def mid_price(self) -> Decimal:
        """Calculate mid price"""
        return (self.bid + self.ask) / 2
    
    @property
    def spread(self) -> Decimal:
        """Calculate bid-ask spread"""
        return self.ask - self.bid
    
    @property
    def spread_percentage(self) -> Decimal:
        """Calculate spread as percentage of mid price"""
        if self.mid_price == 0:
            return Decimal(0)
        return (self.spread / self.mid_price) * 100


class ArbitrageOpportunity(BaseModel):
    """Detected arbitrage opportunity"""
    opportunity_id: str
    type: ArbitrageType
    polymarket: PolymarketMarket
    spot_market: SpotMarket
    
    # Polymarket position details
    polymarket_side: MarketSide  # UP or DOWN
    polymarket_price: Decimal
    polymarket_quantity: Decimal
    
    # Hedge position details
    hedge_side: MarketSide  # LONG or SHORT
    hedge_price: Decimal
    hedge_quantity: Decimal
    
    # Profit calculations
    expected_profit_usd: Decimal
    expected_profit_percentage: Decimal
    breakeven_price: Decimal
    max_risk_usd: Decimal
    
    # Risk metrics
    probability_of_profit: Decimal
    sharpe_ratio: Optional[Decimal] = None
    
    # Timing
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    
    @validator("expected_profit_percentage")
    def validate_profit_percentage(cls, v):
        if v < -100:
            raise ValueError("Profit percentage cannot be less than -100%")
        return v
    
    @property
    def time_value(self) -> Decimal:
        """Calculate time value component of the opportunity"""
        hours_to_expiry = (self.expires_at - datetime.utcnow()).total_seconds() / 3600
        if hours_to_expiry <= 0:
            return Decimal(0)
        # Simple linear decay model - can be improved
        return self.expected_profit_usd * (Decimal(str(hours_to_expiry)) / 24)
    
    @property
    def risk_reward_ratio(self) -> Decimal:
        """Calculate risk/reward ratio"""
        if self.max_risk_usd == 0:
            return Decimal(0)
        return self.expected_profit_usd / self.max_risk_usd


class Position(BaseModel):
    """Active trading position"""
    position_id: str
    opportunity_id: str
    status: PositionStatus = PositionStatus.PENDING
    
    # Polymarket leg
    polymarket_order_id: Optional[str] = None
    polymarket_side: MarketSide
    polymarket_entry_price: Optional[Decimal] = None
    polymarket_quantity: Optional[Decimal] = None
    polymarket_fees: Decimal = Decimal(0)
    
    # Hedge leg
    hedge_order_id: Optional[str] = None
    hedge_exchange: str
    hedge_symbol: str
    hedge_side: MarketSide
    hedge_entry_price: Optional[Decimal] = None
    hedge_quantity: Optional[Decimal] = None
    hedge_fees: Decimal = Decimal(0)
    
    # Risk management
    stop_loss_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    max_loss_usd: Decimal
    
    # Timestamps
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    expires_at: datetime
    
    # P&L
    realized_pnl: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    
    @property
    def is_open(self) -> bool:
        """Check if position is currently open"""
        return self.status in [PositionStatus.OPEN, PositionStatus.PARTIAL]
    
    @property
    def total_fees(self) -> Decimal:
        """Calculate total fees paid"""
        return self.polymarket_fees + self.hedge_fees
    
    @property
    def net_pnl(self) -> Decimal:
        """Calculate net P&L after fees"""
        return self.realized_pnl + self.unrealized_pnl - self.total_fees
    
    @property
    def duration_hours(self) -> float:
        """Calculate position duration in hours"""
        end_time = self.closed_at or datetime.utcnow()
        delta = end_time - self.opened_at
        return delta.total_seconds() / 3600


class TradeSignal(BaseModel):
    """Trading signal for execution"""
    signal_id: str
    opportunity: ArbitrageOpportunity
    action: str  # "ENTER", "EXIT", "ADJUST"
    urgency: str  # "HIGH", "MEDIUM", "LOW"
    confidence: Decimal = Field(ge=0, le=1)
    
    # Execution parameters
    max_slippage_percent: Decimal
    time_in_force: str = "IOC"  # Immediate or Cancel
    
    # Risk checks
    risk_checks_passed: bool = False
    risk_warnings: List[str] = Field(default_factory=list)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    
    @property
    def is_valid(self) -> bool:
        """Check if signal is still valid"""
        return (
            datetime.utcnow() < self.expires_at 
            and self.risk_checks_passed
        )


class PerformanceMetrics(BaseModel):
    """Bot performance metrics"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    total_pnl: Decimal = Decimal(0)
    best_trade: Decimal = Decimal(0)
    worst_trade: Decimal = Decimal(0)
    average_trade: Decimal = Decimal(0)
    
    win_rate: Decimal = Decimal(0)
    profit_factor: Decimal = Decimal(0)
    sharpe_ratio: Decimal = Decimal(0)
    max_drawdown: Decimal = Decimal(0)
    
    total_volume: Decimal = Decimal(0)
    total_fees_paid: Decimal = Decimal(0)
    
    start_date: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    def update_metrics(self, position: Position):
        """Update metrics with a closed position"""
        self.total_trades += 1
        
        if position.net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        self.total_pnl += position.net_pnl
        self.best_trade = max(self.best_trade, position.net_pnl)
        self.worst_trade = min(self.worst_trade, position.net_pnl)
        
        if self.total_trades > 0:
            self.average_trade = self.total_pnl / self.total_trades
            self.win_rate = Decimal(self.winning_trades) / Decimal(self.total_trades)
        
        self.total_fees_paid += position.total_fees
        self.last_updated = datetime.utcnow()
