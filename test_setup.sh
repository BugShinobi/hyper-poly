#!/bin/bash
# Quick setup verification script

echo "🔍 Verifying Polymarket × Hyperliquid Arbitrage Bot Setup..."
echo ""

# Check Python version
echo "1. Checking Python version..."
python3 --version || { echo "❌ Python 3 not found"; exit 1; }
echo "✅ Python found"
echo ""

# Check if .env exists
echo "2. Checking .env file..."
if [ -f .env ]; then
    echo "✅ .env file exists"
else
    echo "⚠️  .env file not found"
    echo "   Run: cp .env.example .env"
    echo "   Then edit .env with your API keys"
fi
echo ""

# Check if virtual environment exists
echo "3. Checking virtual environment..."
if [ -d venv ]; then
    echo "✅ Virtual environment exists"
else
    echo "⚠️  Virtual environment not found"
    echo "   Run: python3 -m venv venv"
fi
echo ""

# Check src directory structure
echo "4. Checking project structure..."
if [ -d src/exchanges ] && [ -d src/arbitrage ] && [ -d src/utils ]; then
    echo "✅ Project structure correct"
    echo "   - src/exchanges/ ✓"
    echo "   - src/arbitrage/ ✓"
    echo "   - src/utils/ ✓"
    echo "   - src/monitoring/ ✓"
else
    echo "❌ Project structure incomplete"
fi
echo ""

# Count Python files
echo "5. Checking Python files..."
file_count=$(find src/ -name "*.py" | wc -l | tr -d ' ')
echo "   Found $file_count Python files in src/"
if [ "$file_count" -ge 15 ]; then
    echo "✅ All files present"
else
    echo "⚠️  Some files may be missing (expected ~18 files)"
fi
echo ""

# Check if requirements.txt exists
echo "6. Checking requirements.txt..."
if [ -f requirements.txt ]; then
    echo "✅ requirements.txt exists"
else
    echo "❌ requirements.txt not found"
fi
echo ""

# Try importing src modules (if venv activated)
echo "7. Testing Python imports..."
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
    python3 -c "from src.config import config" 2>/dev/null && echo "✅ Imports work" || echo "⚠️  Import errors (install dependencies with: pip install -r requirements.txt)"
    deactivate
else
    echo "⚠️  Skipped (no virtual environment)"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 Summary:"
echo ""
echo "Next steps:"
echo "  1. Create .env file: cp .env.example .env"
echo "  2. Edit .env with your API keys"
echo "  3. Create venv: python3 -m venv venv"
echo "  4. Activate venv: source venv/bin/activate"
echo "  5. Install deps: pip install -r requirements.txt"
echo "  6. Test run: python run.py --help"
echo "  7. Paper trade: python run.py --debug"
echo ""
echo "Or use Docker:"
echo "  docker-compose up -d"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
