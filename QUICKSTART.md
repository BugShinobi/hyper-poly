# 🚀 Quick Start Guide

## ✅ What's Ready:

1. ✅ Bot with Polymarket × Hyperliquid integration
2. ✅ Web Dashboard at http://localhost:5000
3. ✅ Docker setup for easy deployment
4. ✅ All dependencies installed

---

## 🎯 Option 1: Run with Dashboard (Recommended)

### Step 1: Start the Dashboard
```bash
# In Terminal 1
source venv/bin/activate
python dashboard_server.py
```

### Step 2: Start the Bot
```bash
# In Terminal 2
source venv/bin/activate
python run.py --live --leverage 2 --assets BTC --strategy passive
```

### Step 3: View Dashboard
Open: http://localhost:5000

You'll see:
- 📊 Real-time statistics
- 💰 Account balances
- 📋 Live logs
- ✅ Bot status

---

## 🐳 Option 2: Run with Docker

### Single Bot:
```bash
docker-compose up -d
docker-compose logs -f arb-bot
```

### Bot + Dashboard:
```bash
docker-compose -f docker-compose-full.yml up -d
```

Then visit: http://localhost:5000

---

## 📋 Commands Cheat Sheet

### Bot Commands:
```bash
# Paper trading (safe)
python run.py --debug --assets BTC

# Live trading
python run.py --live --leverage 2 --strategy passive

# Multiple assets
python run.py --live --assets BTC ETH SOL

# Stop bot
pkill -f "run.py"
```

### Dashboard Commands:
```bash
# Start dashboard
python dashboard_server.py

# Stop dashboard
pkill -f "dashboard_server.py"
```

### Docker Commands:
```bash
# Start everything
docker-compose -f docker-compose-full.yml up -d

# View logs
docker-compose logs -f arb-bot
docker-compose logs -f dashboard

# Stop everything
docker-compose down

# Rebuild
docker-compose up -d --build
```

---

## 🔍 What the Dashboard Shows:

- **Bot Status**: Running / Stopped
- **Total Scans**: How many times it checked for opportunities
- **Opportunities Found**: Number of arb opportunities detected
- **Trades Executed**: Actual trades placed
- **Balances**: Polymarket + Hyperliquid balances
- **Errors**: Any errors encountered
- **Live Logs**: Real-time bot logs

---

## ⚙️ Before Going Live:

1. Fund your accounts:
   - Polymarket: $20+ USDC (Polygon)
   - Hyperliquid: $70+ USDC (Arbitrum)

2. Update `.env` settings for small capital:
```env
MAX_POSITION_SIZE_USD=40
MIN_PROFIT_THRESHOLD_USD=2
DEFAULT_LEVERAGE=2
MAX_CONCURRENT_POSITIONS=1
```

3. Test with paper trading first!

---

## 📊 Example Workflow:

```bash
# Terminal 1: Start Dashboard
source venv/bin/activate
python dashboard_server.py
# Dashboard running at http://localhost:5000

# Terminal 2: Start Bot
source venv/bin/activate
python run.py --live --leverage 2 --assets BTC

# Browser: Open http://localhost:5000
# Watch your bot trade in real-time!
```

---

## 🛑 To Stop Everything:

```bash
# Stop bot
pkill -f "run.py"

# Stop dashboard
pkill -f "dashboard_server.py"

# Or with Docker
docker-compose down
```

---

## 💡 Tips:

- Dashboard updates every 2 seconds
- Logs are stored in `logs/` directory
- Use `--debug` flag to see more details
- Start with small amounts ($20-100)
- Monitor the dashboard for first 24 hours

---

Ready to go! 🎯
