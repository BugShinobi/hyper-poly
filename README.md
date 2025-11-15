# Polymarket × Hyperliquid Arbitrage Bot

An advanced arbitrage trading bot that exploits price inefficiencies between Polymarket's binary prediction markets and Hyperliquid's perpetual futures.

## 📊 Strategy Overview

This bot identifies and executes arbitrage opportunities by:
1. **Betting on binary outcomes** on Polymarket (e.g., "Will BTC be above $100k on Dec 31?")
2. **Hedging with perpetual futures** on Hyperliquid to create a market-neutral position
3. **Profiting from time decay and mispricing** as the markets converge

### Key Advantages
- **Decentralized execution** - Both platforms are decentralized
- **No KYC required** - Trade without identity verification
- **High leverage available** - Up to 50x on Hyperliquid
- **Low fees** - 0.02% maker / 0.03% taker on Hyperliquid
- **Funding rate arbitrage** - Earn funding when shorting in positive funding markets

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Ethereum wallet with private key
- USDC on Polygon (for Polymarket)
- USDC on Hyperliquid L1
- Basic understanding of derivatives trading

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/polymarket-hyperliquid-arb.git
cd polymarket-hyperliquid-arb
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your private keys and settings
```

### Configuration

Edit `.env` file with your credentials:

```env
# Polymarket Configuration
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_PRIVATE_KEY=0x_your_ethereum_private_key

# Hyperliquid Configuration  
HYPERLIQUID_PRIVATE_KEY=0x_your_private_key
HYPERLIQUID_IS_MAINNET=true  # false for testnet

# Trading Parameters
MAX_POSITION_SIZE_USD=5000
MIN_PROFIT_THRESHOLD_USD=50
DEFAULT_LEVERAGE=5  # 1-50
MAX_LEVERAGE=10
FUNDING_RATE_THRESHOLD=0.01  # 1%
```

## 💻 Usage

### Paper Trading (Recommended to start)
```bash
python run.py
```

### Live Trading
```bash
python run.py --live
```

### Advanced Options
```bash
# Trade specific assets
python run.py --assets BTC ETH SOL

# Use different execution strategy
python run.py --strategy twap  # Options: aggressive, passive, adaptive, twap

# Set custom leverage
python run.py --leverage 10

# Use testnet
python run.py --testnet

# Enable debug logging
python run.py --debug
```

## 📊 Web Dashboard

Monitor your bot in real-time with the included web dashboard:

```bash
# Terminal 1: Start the dashboard
python dashboard_server.py

# Terminal 2: Start the bot
python run.py --live --leverage 2 --assets BTC
```

Then open http://localhost:5000 in your browser to see:
- Bot status (running/stopped)
- Total scans and opportunities found
- Trades executed
- Account balances (Polymarket + Hyperliquid)
- Live error tracking
- Real-time log stream

**Docker with Dashboard:**
```bash
docker-compose -f docker-compose-full.yml up -d
```

See [QUICKSTART.md](QUICKSTART.md) for more dashboard options.

## 📈 Trading Strategies

### 1. **Adaptive (Default)**
- Adjusts execution based on market conditions
- Uses market orders near expiry
- Balances speed vs price improvement

### 2. **Aggressive**
- Market orders for fast execution
- Best for high-probability setups
- Higher slippage tolerance

### 3. **Passive**
- Limit orders only
- Post-only on Hyperliquid (maker fees)
- Best for low volatility periods

### 4. **TWAP (Time-Weighted Average Price)**
- Splits large orders into chunks
- Reduces market impact
- Best for size >$5000

## 🔍 How It Works

### Opportunity Detection
The bot continuously scans for arbitrage opportunities by:
1. Fetching active Polymarket "Up or Down" markets
2. Getting current Hyperliquid perpetual prices
3. Calculating expected profit considering:
   - Polymarket outcome probabilities
   - Hedge costs on Hyperliquid
   - Funding rates
   - Time decay
   - Transaction fees

### Position Execution
When a profitable opportunity is found:
1. **Pre-execution checks** - Verify liquidity, balances, risk limits
2. **Parallel execution** - Place orders on both platforms simultaneously
3. **Risk management** - Set stop-loss and take-profit levels
4. **Position monitoring** - Track P&L and market conditions

### Risk Management
- **Position limits** - Maximum concurrent positions
- **Daily loss limits** - Stop trading after max daily loss
- **Leverage controls** - Dynamic leverage based on opportunity
- **Funding rate monitoring** - Exit if funding becomes extreme
- **Automatic position closing** - At market expiry or stop-loss

## 📊 Example Trade

```
Market: "Will BTC be above $100,000 on Dec 31?"
Current BTC Price: $96,500
Polymarket "Down" Price: 0.75 (75% chance BTC stays below $100k)

Strategy:
1. Buy 1000 "Down" shares at 0.75 = $750 cost
2. Open LONG position on Hyperliquid: 0.0078 BTC ($750 value)
3. Use 5x leverage = $150 margin required

Scenarios:
- If BTC stays below $100k: Win $250 on Polymarket, lose on hedge
- If BTC goes above $100k: Lose $750 on Polymarket, profit on hedge
- Profit comes from time decay and probability mispricing
```

## 🛡️ Safety Features

### Capital Protection
- Never risks more than configured max position size
- Automatic position sizing based on liquidity
- Stop-loss orders on all positions
- Circuit breakers for extreme market conditions

### Execution Safety
- Slippage protection
- Order timeout mechanisms  
- Automatic rollback of failed trades
- Position reconciliation

### Monitoring
- Real-time P&L tracking
- Telegram notifications (optional)
- Performance metrics dashboard
- Detailed trade logging

## 📈 Performance Metrics

The bot tracks:
- **Win rate** - Percentage of profitable trades
- **Average profit** - Per trade statistics
- **Sharpe ratio** - Risk-adjusted returns
- **Maximum drawdown** - Largest peak-to-trough decline
- **Execution metrics** - Slippage, fill rates, timing

## ⚠️ Risks

### Market Risks
- **Binary risk** - Polymarket positions can go to 0
- **Liquidation risk** - Leveraged positions can be liquidated
- **Funding rate risk** - Can turn negative quickly
- **Slippage** - Large orders may move the market

### Technical Risks  
- **Smart contract risk** - Both platforms use smart contracts
- **Network congestion** - Can delay execution
- **Oracle risk** - Price feed discrepancies
- **Platform risk** - Exchange downtime or issues

### Mitigation
- Start with small positions
- Use stop-losses religiously
- Monitor funding rates
- Diversify across multiple markets
- Keep leverage reasonable

## 🔧 Advanced Configuration

### Database Setup (Optional)
```bash
# PostgreSQL for trade history
DATABASE_URL=postgresql://user:pass@localhost/arb_bot

# Redis for caching
REDIS_URL=redis://localhost:6379
```

### Telegram Alerts
```env
ENABLE_TELEGRAM_ALERTS=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 📝 Development

### Project Structure
```
polymarket-hyperliquid-arb/
├── src/
│   ├── arbitrage/
│   │   ├── hyperliquid_detector.py  # Opportunity detection
│   │   └── hyperliquid_executor.py  # Trade execution
│   ├── exchanges/
│   │   ├── polymarket_client.py     # Polymarket API
│   │   └── hyperliquid_client.py    # Hyperliquid API
│   ├── models.py                    # Data models
│   ├── config.py                    # Configuration
│   └── main.py                      # Bot orchestrator
├── tests/
├── logs/
├── run.py                           # Entry point
└── requirements.txt
```

### Testing
```bash
# Run tests
pytest tests/

# Run with mock data
python run.py --paper --debug
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📜 License

MIT License - See LICENSE file for details

## ⚡ Disclaimer

**This software is for educational purposes only.**

Trading cryptocurrencies and derivatives carries substantial risk of loss. This bot is experimental software and may contain bugs. Never trade with funds you cannot afford to lose. The authors are not responsible for any financial losses incurred through use of this software.

Always:
- Test thoroughly on testnet first
- Start with small position sizes
- Monitor the bot actively
- Understand the code before running with real funds
- Consider tax implications of your trades

## 🔗 Resources

- [Polymarket Documentation](https://docs.polymarket.com)
- [Hyperliquid Documentation](https://docs.hyperliquid.xyz)
- [Arbitrage Trading Strategies](https://en.wikipedia.org/wiki/Arbitrage)
- [Understanding Funding Rates](https://www.binance.com/en/support/faq/360033525031)

## 💬 Support

- GitHub Issues: [Report bugs](https://github.com/yourusername/repo/issues)
- Discord: [Join community](https://discord.gg/yourserver)
- Twitter: [@yourhandle](https://twitter.com/yourhandle)

---

Built with ❤️ for the DeFi community
