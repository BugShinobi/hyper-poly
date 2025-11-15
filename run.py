#!/usr/bin/env python3
"""
Startup script for the Polymarket × Hyperliquid Arbitrage Bot
"""
import os
import sys
import argparse
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.main import ArbitrageBot
from src.arbitrage.hyperliquid_executor import ExecutionStrategy
from src.utils.logger import setup_logging, console
from src.config import config


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Polymarket × Hyperliquid Arbitrage Bot - Trade between prediction and perpetual markets"
    )
    
    parser.add_argument(
        "--assets",
        type=str,
        nargs="+",
        default=["BTC", "ETH"],
        help="Assets to trade (default: BTC ETH)"
    )
    
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["aggressive", "passive", "adaptive", "twap"],
        default="adaptive",
        help="Execution strategy (default: adaptive)"
    )
    
    parser.add_argument(
        "--leverage",
        type=int,
        default=None,
        help="Override default leverage (1-50)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (default: paper trading)"
    )
    
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Hyperliquid testnet"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom config file"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point"""
    args = parse_arguments()
    
    # Override config if needed
    if args.leverage:
        config.DEFAULT_LEVERAGE = min(50, max(1, args.leverage))
    
    if args.testnet:
        config.HYPERLIQUID_IS_MAINNET = False
    
    # Setup logging
    log_level = "DEBUG" if args.debug else config.LOG_LEVEL
    setup_logging(level=log_level, environment=config.ENVIRONMENT)
    
    # Print startup banner
    console.print("[bold cyan]╔══════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Polymarket × Hyperliquid Arbitrage Bot v1.0.0  ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════╝[/bold cyan]")
    console.print()
    
    # Display configuration
    console.print("[bold]Configuration:[/bold]")
    console.print(f"  • Assets: {', '.join(args.assets)}")
    console.print(f"  • Strategy: {args.strategy}")
    console.print(f"  • Leverage: {config.DEFAULT_LEVERAGE}x (max: {config.MAX_LEVERAGE}x)")
    console.print(f"  • Mode: {'[bold red]LIVE TRADING[/bold red]' if args.live else '[bold green]Paper Trading[/bold green]'}")
    console.print(f"  • Network: {'[cyan]Mainnet[/cyan]' if config.HYPERLIQUID_IS_MAINNET else '[yellow]Testnet[/yellow]'}")
    console.print(f"  • Max Position: ${config.MAX_POSITION_SIZE_USD}")
    console.print(f"  • Min Profit: ${config.MIN_PROFIT_THRESHOLD_USD}")
    console.print(f"  • Funding Threshold: {config.FUNDING_RATE_THRESHOLD:.2%}")
    console.print()
    
    # Safety check for live trading
    if args.live:
        console.print("[bold red]⚠️  WARNING: Live trading is enabled![/bold red]")
        console.print("[yellow]Real money will be at risk. Are you sure?[/yellow]")
        console.print("[yellow]Make sure you have:[/yellow]")
        console.print("  • Funded Polymarket account on Polygon")
        console.print("  • Funded Hyperliquid account")
        console.print("  • Correct private keys in .env")
        console.print()
        confirmation = input("Type 'YES' to continue: ")
        
        if confirmation != "YES":
            console.print("[red]Live trading cancelled.[/red]")
            return
    
    # Map strategy string to enum
    strategy_map = {
        "aggressive": ExecutionStrategy.AGGRESSIVE,
        "passive": ExecutionStrategy.PASSIVE,
        "adaptive": ExecutionStrategy.ADAPTIVE,
        "twap": ExecutionStrategy.TWAP
    }
    
    # Create and start bot
    bot = ArbitrageBot(
        assets=args.assets,
        execution_strategy=strategy_map[args.strategy],
        enable_live_trading=args.live
    )
    
    try:
        console.print("[green]Starting bot...[/green]\n")
        await bot.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        await bot.shutdown()
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
