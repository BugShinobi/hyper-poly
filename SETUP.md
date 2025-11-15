# Setup Guide - Polymarket × Hyperliquid Arbitrage Bot

This guide covers both **Docker** and **native Python** setup methods.

---

## 🚀 Quick Start (Choose Your Path)

### Option 1: Docker (Recommended for Production)

**Prerequisites:**
- Docker installed ([Get Docker](https://docs.docker.com/get-docker/))
- Docker Compose installed (comes with Docker Desktop)

**Steps:**
```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys and settings

# 2. Build and run
docker-compose up -d

# 3. View logs
docker-compose logs -f arb-bot

# 4. Stop the bot
docker-compose down
```

### Option 2: Native Python (Better for Development)

**Prerequisites:**
- Python 3.11+ installed
- pip package manager

**Steps:**
```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys and settings

# 4. Run the bot
python run.py --debug
```

---

## 🔑 Configuration

### 1. Get Your API Keys

**Polymarket:**
1. Sign up at [polymarket.com](https://polymarket.com)
2. Go to Account → API Keys
3. Create new API key
4. Save the key and secret

**Hyperliquid:**
1. You need an Ethereum wallet with funds
2. Your private key is used for signing transactions
3. Transfer USDC to your Hyperliquid account

### 2. Edit `.env` File

```env
# Polymarket
POLYMARKET_API_KEY=your_actual_api_key
POLYMARKET_API_SECRET=your_actual_secret
POLYMARKET_PRIVATE_KEY=0xyour_ethereum_private_key

# Hyperliquid
HYPERLIQUID_PRIVATE_KEY=0xyour_ethereum_private_key
HYPERLIQUID_IS_MAINNET=true  # Use false for testnet

# Trading (start small!)
MAX_POSITION_SIZE_USD=1000
MIN_PROFIT_THRESHOLD_USD=20
DEFAULT_LEVERAGE=3
```

---

## 🐳 Docker Commands

### Development Mode (with live code updates)
```bash
# docker-compose.yml - uncomment the volume mount line:
# volumes:
#   - ./src:/app/src

docker-compose up
```

### Production Mode
```bash
# Build and start in background
docker-compose up -d

# View logs
docker-compose logs -f

# Restart bot
docker-compose restart arb-bot

# Stop everything
docker-compose down

# Rebuild after code changes
docker-compose up -d --build
```

### Useful Docker Commands
```bash
# Enter container shell
docker exec -it polymarket-hyperliquid-bot bash

# View resource usage
docker stats polymarket-hyperliquid-bot

# View logs from specific time
docker-compose logs --since 1h arb-bot

# Remove everything (including volumes)
docker-compose down -v
```

---

## 🐍 Native Python Commands

### Running the Bot

```bash
# Paper trading (no real money)
python run.py

# Paper trading with debug logs
python run.py --debug

# Live trading (CAREFUL!)
python run.py --live

# Specific assets
python run.py --assets BTC ETH SOL

# Custom leverage
python run.py --leverage 5

# Different strategy
python run.py --strategy aggressive  # Options: aggressive, passive, adaptive, twap

# Testnet mode
python run.py --testnet

# Combine flags
python run.py --live --leverage 3 --assets BTC --strategy adaptive
```

### Development

```bash
# Run with auto-reload (for development)
# Install watchdog first: pip install watchdog
watchmedo auto-restart -d src -p '*.py' -- python run.py --debug

# Run tests (when you add them)
pytest tests/

# Check code style
black src/
flake8 src/
```

---

## 📊 Monitoring

### Logs Location

**Docker:**
- Container logs: `docker-compose logs -f arb-bot`
- Persistent logs: `./logs/` directory (mounted volume)

**Native Python:**
- `./logs/bot_YYYYMMDD.log` - All logs
- `./logs/trades_YYYYMMDD.log` - Trade-specific logs

### Telegram Alerts (Optional)

1. Create a Telegram bot via [@BotFather](https://t.me/botfather)
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`:
```env
ENABLE_TELEGRAM_ALERTS=true
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
```

---

## ⚠️ Safety Checklist

Before going live with real money:

- [ ] Test on **testnet** first (`--testnet` flag)
- [ ] Start with **small position sizes** ($100-500)
- [ ] Use **low leverage** (3-5x max)
- [ ] Monitor the bot for **24 hours** in paper trading
- [ ] Understand the **risks** - you can lose money
- [ ] Have **stop-loss** enabled (check config)
- [ ] Set **MAX_DAILY_LOSS_USD** conservatively
- [ ] Enable **Telegram alerts** for monitoring
- [ ] Keep **sufficient balance** on both platforms
- [ ] Understand **funding rates** on Hyperliquid

---

## 🔧 Troubleshooting

### "ModuleNotFoundError"
```bash
# Native Python:
pip install -r requirements.txt

# Docker:
docker-compose build --no-cache
```

### "Connection refused" errors
- Check your internet connection
- Verify RPC URLs in `.env` are accessible
- Try different RPC endpoints

### "Insufficient balance" errors
- Add USDC to Polymarket (Polygon network)
- Add USDC to Hyperliquid
- Lower MAX_POSITION_SIZE_USD

### Bot not finding opportunities
- This is normal - opportunities are rare
- Try lowering MIN_PROFIT_THRESHOLD_USD
- Check if markets exist for your assets
- Verify both exchanges are accessible

### High funding rates warning
- This is expected - Hyperliquid funding changes frequently
- Adjust FUNDING_RATE_THRESHOLD if needed
- Bot will skip trades with extreme funding

---

## 📈 Performance Tuning

### For Better Execution:
```env
# More aggressive (faster but more slippage)
MAX_SLIPPAGE_PERCENT=1.0
--strategy aggressive

# More passive (better prices but may miss trades)
MAX_SLIPPAGE_PERCENT=0.2
--strategy passive

# Adaptive (recommended)
--strategy adaptive
```

### For More Opportunities:
```env
MIN_PROFIT_THRESHOLD_USD=20  # Lower threshold
MAX_POSITION_SIZE_USD=10000  # Bigger positions
```

### For Safety:
```env
MAX_CONCURRENT_POSITIONS=3   # Fewer simultaneous trades
MAX_DAILY_TRADES=10          # Limit daily activity
MAX_DAILY_LOSS_USD=200       # Circuit breaker
DEFAULT_LEVERAGE=2           # Lower leverage
```

---

## 🚀 Deployment to VPS

### Recommended VPS Providers:
- **DigitalOcean** - $6/month droplet is enough
- **AWS EC2** - t3.micro free tier eligible
- **Linode** - $5/month plan works
- **Vultr** - Good for crypto-friendly locations

### Quick Deploy:
```bash
# SSH to your VPS
ssh user@your-server-ip

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Clone your repo (if using git)
git clone your-repo-url
cd hyper-poly

# Setup and run
cp .env.example .env
nano .env  # Add your keys
docker-compose up -d

# Enable auto-restart on server reboot
docker update --restart unless-stopped polymarket-hyperliquid-bot
```

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/hyper-poly/issues)
- **Docs**: See [README.md](README.md)
- **Hyperliquid Docs**: [docs.hyperliquid.xyz](https://docs.hyperliquid.xyz)
- **Polymarket Docs**: [docs.polymarket.com](https://docs.polymarket.com)

---

**Remember**: This is experimental software. Never trade with money you can't afford to lose!
