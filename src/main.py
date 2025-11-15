"""
Main arbitrage bot orchestrator
"""
import asyncio
import signal
import sys
from typing import List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from src.config import config
from src.utils.logger import bot_logger, console, setup_logging
from src.models import (
    ArbitrageOpportunity,
    Position,
    PerformanceMetrics,
    TradeSignal
)
from src.exchanges.polymarket_client import PolymarketClient
from src.exchanges.hyperliquid_client import HyperliquidClient
from src.arbitrage.hyperliquid_detector import HyperliquidArbitrageDetector
from src.arbitrage.hyperliquid_executor import HyperliquidExecutor, ExecutionStrategy
from src.monitoring.dashboard import Dashboard
from src.utils.notifications import NotificationManager
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel


class ArbitrageBot:
    """Main arbitrage bot orchestrator"""
    
    def __init__(
        self,
        assets: List[str] = ["BTC", "ETH"],
        execution_strategy: ExecutionStrategy = ExecutionStrategy.ADAPTIVE,
        enable_live_trading: bool = False
    ):
        """
        Initialize the arbitrage bot
        
        Args:
            assets: List of assets to trade
            execution_strategy: Execution strategy to use
            enable_live_trading: Whether to execute real trades
        """
        self.assets = assets
        self.enable_live_trading = enable_live_trading
        self.is_running = False
        
        # Initialize components
        bot_logger.info("Initializing arbitrage bot...")

        self.polymarket = PolymarketClient()
        self.hyperliquid = HyperliquidClient()
        self.detector = HyperliquidArbitrageDetector(self.polymarket, self.hyperliquid)
        self.executor = HyperliquidExecutor(
            self.polymarket,
            self.hyperliquid,
            execution_strategy
        )
        
        # Performance tracking
        self.metrics = PerformanceMetrics()
        self.opportunities_found = 0
        self.opportunities_executed = 0
        
        # Notification manager
        self.notifications = NotificationManager() if config.ENABLE_TELEGRAM_ALERTS else None
        
        # Dashboard (if enabled)
        self.dashboard = Dashboard() if not enable_live_trading else None
        
        bot_logger.info(
            f"Bot initialized - Assets: {assets}, "
            f"Live trading: {enable_live_trading}, "
            f"Strategy: {execution_strategy}"
        )
    
    async def start(self):
        """Start the arbitrage bot"""
        bot_logger.info("Starting arbitrage bot...")
        self.is_running = True
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Initialize exchange and Polymarket connections
            async with self.polymarket, self.hyperliquid:
                # Start background tasks
                tasks = [
                    asyncio.create_task(self._main_loop()),
                    asyncio.create_task(self.executor.monitor_positions()),
                    asyncio.create_task(self._monitor_performance())
                ]
                
                if self.dashboard:
                    tasks.append(asyncio.create_task(self._update_dashboard()))
                
                # Wait for all tasks
                await asyncio.gather(*tasks)
                
        except Exception as e:
            bot_logger.error(f"Critical error in bot: {e}")
            await self.shutdown()
    
    async def _main_loop(self):
        """Main trading loop"""
        scan_interval = 30  # Scan every 30 seconds
        
        while self.is_running:
            try:
                # Check account balances
                await self._check_balances()
                
                # Scan for opportunities
                bot_logger.info("Scanning for arbitrage opportunities...")
                opportunities = await self.detector.scan_for_opportunities(self.assets)
                
                self.opportunities_found += len(opportunities)
                
                if opportunities:
                    bot_logger.info(f"Found {len(opportunities)} opportunities")
                    
                    # Process each opportunity
                    for opportunity in opportunities[:3]:  # Process top 3
                        await self._process_opportunity(opportunity)
                else:
                    bot_logger.debug("No profitable opportunities found")
                
                # Sleep before next scan
                await asyncio.sleep(scan_interval)
                
            except Exception as e:
                bot_logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(scan_interval)
    
    async def _process_opportunity(self, opportunity: ArbitrageOpportunity):
        """Process a single arbitrage opportunity"""
        try:
            # Log opportunity details
            self._log_opportunity(opportunity)
            
            # Validate opportunity
            is_valid, warnings = await self.detector.validate_opportunity(opportunity)
            
            if warnings:
                for warning in warnings:
                    bot_logger.warning(f"Validation warning: {warning}")
            
            if not is_valid:
                bot_logger.info(f"Opportunity {opportunity.opportunity_id} failed validation")
                return
            
            # Create trade signal
            signal = TradeSignal(
                signal_id=opportunity.opportunity_id,
                opportunity=opportunity,
                action="ENTER",
                urgency="HIGH" if opportunity.time_value.total_seconds() < 7200 else "MEDIUM",
                confidence=opportunity.probability_of_profit,
                max_slippage_percent=config.MAX_SLIPPAGE_PERCENT,
                risk_checks_passed=is_valid,
                risk_warnings=warnings,
                expires_at=opportunity.expires_at
            )
            
            # Execute if live trading is enabled
            if self.enable_live_trading and signal.is_valid:
                bot_logger.info(f"Executing opportunity {opportunity.opportunity_id}")
                
                position = await self.executor.execute_opportunity(opportunity)
                
                if position:
                    self.opportunities_executed += 1
                    
                    # Send notification
                    if self.notifications:
                        await self.notifications.send_trade_alert(position)
                    
                    bot_logger.info(
                        f"Successfully executed opportunity - Position: {position.position_id}"
                    )
                else:
                    bot_logger.error(f"Failed to execute opportunity {opportunity.opportunity_id}")
            else:
                bot_logger.info(
                    f"Paper trade: Would execute {opportunity.polymarket.asset} "
                    f"{opportunity.polymarket_side.value} for ${opportunity.expected_profit_usd:.2f} profit"
                )
        
        except Exception as e:
            bot_logger.error(f"Error processing opportunity: {e}")
    
    def _log_opportunity(self, opp: ArbitrageOpportunity):
        """Log opportunity details in a formatted way"""
        table = Table(title=f"Opportunity: {opp.opportunity_id[:8]}")
        
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Asset", opp.polymarket.asset)
        table.add_row("Polymarket Side", opp.polymarket_side.value)
        table.add_row("Polymarket Price", f"{opp.polymarket_price:.4f}")
        table.add_row("Hedge Side", opp.hedge_side.value)
        table.add_row("Hedge Price", f"${opp.hedge_price:.2f}")
        table.add_row("Expected Profit", f"${opp.expected_profit_usd:.2f}")
        table.add_row("Profit %", f"{opp.expected_profit_percentage:.2f}%")
        table.add_row("Probability", f"{opp.probability_of_profit:.1%}")
        table.add_row("Max Risk", f"${opp.max_risk_usd:.2f}")
        table.add_row("Expires", opp.expires_at.strftime("%Y-%m-%d %H:%M"))
        
        console.print(table)
    
    async def _check_balances(self):
        """Check and log account balances"""
        try:
            pm_balance = await self.polymarket.get_balance()
            hl_balance = await self.hyperliquid.get_balance()

            total_balance = pm_balance + hl_balance

            bot_logger.debug(
                f"Balances - Polymarket: ${pm_balance:.2f}, "
                f"Hyperliquid: ${hl_balance:.2f}, "
                f"Total: ${total_balance:.2f}"
            )
            
            # Warning if balance is low
            if total_balance < 1000:
                bot_logger.warning(f"Low balance warning: ${total_balance:.2f}")
                
        except Exception as e:
            bot_logger.error(f"Error checking balances: {e}")
    
    async def _monitor_performance(self):
        """Monitor and update performance metrics"""
        update_interval = 300  # Update every 5 minutes
        
        while self.is_running:
            try:
                # Update metrics from closed positions
                for position in self.executor.position_history:
                    if position.status == "CLOSED" and position.net_pnl != 0:
                        self.metrics.update_metrics(position)
                
                # Calculate additional metrics
                if self.metrics.total_trades > 0:
                    # Success rate
                    success_rate = self.opportunities_executed / self.opportunities_found if self.opportunities_found > 0 else 0
                    
                    bot_logger.info(
                        f"Performance Update - "
                        f"Trades: {self.metrics.total_trades}, "
                        f"Win Rate: {self.metrics.win_rate:.1%}, "
                        f"Total P&L: ${self.metrics.total_pnl:.2f}, "
                        f"Opportunities Found: {self.opportunities_found}, "
                        f"Executed: {self.opportunities_executed} ({success_rate:.1%})"
                    )
                
                await asyncio.sleep(update_interval)
                
            except Exception as e:
                bot_logger.error(f"Error monitoring performance: {e}")
                await asyncio.sleep(update_interval)
    
    async def _update_dashboard(self):
        """Update live dashboard (for paper trading)"""
        if not self.dashboard:
            return
        
        with Live(self.dashboard.get_layout(), refresh_per_second=1) as live:
            while self.is_running:
                try:
                    # Update dashboard data
                    self.dashboard.update(
                        opportunities=self.detector.last_opportunities,
                        positions=list(self.executor.active_positions.values()),
                        metrics=self.metrics
                    )
                    
                    # Refresh display
                    live.update(self.dashboard.get_layout())
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    bot_logger.error(f"Dashboard error: {e}")
                    await asyncio.sleep(5)
    
    def _signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        bot_logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(self.shutdown())
    
    async def shutdown(self):
        """Gracefully shutdown the bot"""
        bot_logger.info("Shutting down arbitrage bot...")
        self.is_running = False
        
        try:
            # Close all open positions if in live trading
            if self.enable_live_trading:
                for position in list(self.executor.active_positions.values()):
                    await self.executor.close_position(position, reason="Shutdown")
            
            # Final performance report
            self._print_final_report()
            
            # Close connections
            await self.polymarket.__aexit__(None, None, None)
            await self.hyperliquid.close()
            
        except Exception as e:
            bot_logger.error(f"Error during shutdown: {e}")
        
        bot_logger.info("Bot shutdown complete")
        sys.exit(0)
    
    def _print_final_report(self):
        """Print final performance report"""
        console.print("\n[bold cyan]Final Performance Report[/bold cyan]")
        console.print("=" * 50)
        
        table = Table(show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Opportunities Found", str(self.opportunities_found))
        table.add_row("Opportunities Executed", str(self.opportunities_executed))
        table.add_row("Total Trades", str(self.metrics.total_trades))
        table.add_row("Winning Trades", str(self.metrics.winning_trades))
        table.add_row("Losing Trades", str(self.metrics.losing_trades))
        table.add_row("Win Rate", f"{self.metrics.win_rate:.1%}")
        table.add_row("Total P&L", f"${self.metrics.total_pnl:.2f}")
        table.add_row("Best Trade", f"${self.metrics.best_trade:.2f}")
        table.add_row("Worst Trade", f"${self.metrics.worst_trade:.2f}")
        table.add_row("Average Trade", f"${self.metrics.average_trade:.2f}")
        table.add_row("Total Fees Paid", f"${self.metrics.total_fees_paid:.2f}")
        
        console.print(table)


async def main():
    """Main entry point"""
    # Setup logging
    setup_logging(level=config.LOG_LEVEL, environment=config.ENVIRONMENT)
    
    # Print startup banner
    console.print("[bold cyan]Polymarket Arbitrage Bot[/bold cyan]")
    console.print(f"Version: 1.0.0")
    console.print(f"Environment: {config.ENVIRONMENT}")
    console.print(f"Live Trading: {config.ENVIRONMENT == 'production'}")
    console.print("=" * 50)
    
    # Create and start bot
    bot = ArbitrageBot(
        assets=["BTC", "ETH"],
        execution_strategy=ExecutionStrategy.ADAPTIVE,
        enable_live_trading=(config.ENVIRONMENT == "production")
    )
    
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
