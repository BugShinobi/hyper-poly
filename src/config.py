"""
Configuration management for the arbitrage bot
"""
from typing import Optional, Dict
from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator


class TradingConfig(BaseSettings):
    """Trading configuration and settings"""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True
    )
    
    # Polymarket Configuration
    POLYMARKET_API_KEY: str
    POLYMARKET_API_SECRET: str
    POLYMARKET_PRIVATE_KEY: str
    POLYMARKET_CHAIN_ID: int = 137
    
    # Hyperliquid Configuration
    HYPERLIQUID_PRIVATE_KEY: str
    HYPERLIQUID_API_WALLET: Optional[str] = None
    HYPERLIQUID_IS_MAINNET: bool = True
    HYPERLIQUID_RPC_URL: str = "https://api.hyperliquid.xyz"
    
    # Web3 Configuration
    POLYGON_RPC_URL: str = "https://polygon-rpc.com/"
    ETH_RPC_URL: Optional[str] = None
    
    # Database
    DATABASE_URL: Optional[str] = None
    REDIS_URL: str = "redis://localhost:6379"
    
    # Trading Parameters
    MAX_POSITION_SIZE_USD: Decimal = Field(default=Decimal("5000"))
    MIN_PROFIT_THRESHOLD_USD: Decimal = Field(default=Decimal("50"))
    MAX_SLIPPAGE_PERCENT: Decimal = Field(default=Decimal("0.5"))
    DEFAULT_STOP_LOSS_PERCENT: Decimal = Field(default=Decimal("2.0"))
    DEFAULT_TAKE_PROFIT_PERCENT: Decimal = Field(default=Decimal("1.5"))
    
    # Hyperliquid Specific
    DEFAULT_LEVERAGE: int = Field(default=5, ge=1, le=50)
    MAX_LEVERAGE: int = Field(default=10, ge=1, le=50)
    FUNDING_RATE_THRESHOLD: Decimal = Field(default=Decimal("0.01"))
    POSITION_SIZE_PCT: Decimal = Field(default=Decimal("0.1"))
    
    # Risk Management
    MAX_DAILY_TRADES: int = 20
    MAX_CONCURRENT_POSITIONS: int = 5
    MAX_DAILY_LOSS_USD: Decimal = Field(default=Decimal("500"))
    
    # Monitoring
    ENABLE_TELEGRAM_ALERTS: bool = False
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    
    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    @validator("MAX_SLIPPAGE_PERCENT", "DEFAULT_STOP_LOSS_PERCENT", "DEFAULT_TAKE_PROFIT_PERCENT")
    def validate_percentages(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v
    
    @validator("MAX_POSITION_SIZE_USD", "MIN_PROFIT_THRESHOLD_USD", "MAX_DAILY_LOSS_USD")
    def validate_positive_amounts(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v
    
    @validator("DEFAULT_LEVERAGE", "MAX_LEVERAGE")
    def validate_leverage(cls, v):
        if v < 1 or v > 50:
            raise ValueError("Leverage must be between 1 and 50")
        return v
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def slippage_decimal(self) -> Decimal:
        """Convert slippage percentage to decimal for calculations"""
        return self.MAX_SLIPPAGE_PERCENT / 100
    
    @property
    def stop_loss_decimal(self) -> Decimal:
        """Convert stop loss percentage to decimal for calculations"""
        return self.DEFAULT_STOP_LOSS_PERCENT / 100
    
    @property
    def take_profit_decimal(self) -> Decimal:
        """Convert take profit percentage to decimal for calculations"""
        return self.DEFAULT_TAKE_PROFIT_PERCENT / 100
    
    @property
    def hyperliquid_fees(self) -> Dict[str, Decimal]:
        """Hyperliquid fee structure"""
        return {
            "maker": Decimal("0.0002"),  # 0.02%
            "taker": Decimal("0.0003"),  # 0.03%
        }


# Singleton instance
config = TradingConfig()
