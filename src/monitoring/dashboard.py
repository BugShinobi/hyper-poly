"""
Real-time dashboard for monitoring bot performance
"""
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.models import ArbitrageOpportunity, Position, PerformanceMetrics


class Dashboard:
    """Real-time performance dashboard using Rich"""

    def __init__(self):
        """Initialize dashboard"""
        self.layout = Layout()
        self.opportunities: List[ArbitrageOpportunity] = []
        self.positions: List[Position] = []
        self.metrics: Optional[PerformanceMetrics] = None

        self._setup_layout()

    def _setup_layout(self):
        """Setup dashboard layout"""
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )

        self.layout["main"].split_row(
            Layout(name="opportunities"),
            Layout(name="positions"),
            Layout(name="metrics")
        )

    def update(
        self,
        opportunities: List[ArbitrageOpportunity],
        positions: List[Position],
        metrics: PerformanceMetrics
    ):
        """Update dashboard with new data"""
        self.opportunities = opportunities[:5]  # Top 5 opportunities
        self.positions = positions[:5]  # Top 5 active positions
        self.metrics = metrics

    def get_layout(self) -> Layout:
        """Get the current dashboard layout"""
        # Header
        header_text = Text("Polymarket × Hyperliquid Arbitrage Bot", justify="center", style="bold cyan")
        self.layout["header"].update(Panel(header_text, border_style="cyan"))

        # Opportunities
        self.layout["opportunities"].update(
            Panel(self._render_opportunities(), title="Opportunities", border_style="green")
        )

        # Active Positions
        self.layout["positions"].update(
            Panel(self._render_positions(), title="Active Positions", border_style="yellow")
        )

        # Performance Metrics
        self.layout["metrics"].update(
            Panel(self._render_metrics(), title="Performance", border_style="blue")
        )

        # Footer
        footer_text = Text(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", justify="center")
        self.layout["footer"].update(Panel(footer_text, border_style="dim"))

        return self.layout

    def _render_opportunities(self) -> Table:
        """Render opportunities table"""
        table = Table(show_header=True, header_style="bold green", expand=True)

        table.add_column("Asset", style="cyan", width=6)
        table.add_column("Side", width=5)
        table.add_column("Profit", justify="right", width=8)
        table.add_column("Prob", justify="right", width=6)
        table.add_column("Expires", width=10)

        if not self.opportunities:
            table.add_row("No opportunities found", "", "", "", "")
            return table

        for opp in self.opportunities:
            profit_color = "green" if opp.expected_profit_usd > 100 else "yellow"
            table.add_row(
                opp.polymarket.asset,
                opp.polymarket_side.value[:4],
                f"[{profit_color}]${opp.expected_profit_usd:.0f}[/{profit_color}]",
                f"{opp.probability_of_profit:.0%}",
                opp.expires_at.strftime("%m/%d %H:%M")
            )

        return table

    def _render_positions(self) -> Table:
        """Render active positions table"""
        table = Table(show_header=True, header_style="bold yellow", expand=True)

        table.add_column("ID", width=8)
        table.add_column("Asset", width=6)
        table.add_column("P&L", justify="right", width=10)
        table.add_column("Age", justify="right", width=8)

        if not self.positions:
            table.add_row("No active positions", "", "", "")
            return table

        for pos in self.positions:
            pnl = pos.net_pnl
            pnl_color = "green" if pnl >= 0 else "red"
            pnl_text = f"[{pnl_color}]{'+' if pnl >= 0 else ''}${pnl:.2f}[/{pnl_color}]"

            age_hours = pos.duration_hours
            age_text = f"{age_hours:.1f}h"

            table.add_row(
                pos.position_id[:8],
                pos.hedge_symbol.split("-")[0],
                pnl_text,
                age_text
            )

        return table

    def _render_metrics(self) -> Table:
        """Render performance metrics table"""
        table = Table(show_header=False, expand=True, box=None)

        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right", style="bold")

        if not self.metrics:
            table.add_row("No data yet", "")
            return table

        # Win rate color
        win_rate_color = "green" if self.metrics.win_rate > 0.6 else "yellow" if self.metrics.win_rate > 0.4 else "red"

        # P&L color
        pnl_color = "green" if self.metrics.total_pnl > 0 else "red"

        table.add_row("Total Trades", str(self.metrics.total_trades))
        table.add_row(
            "Win Rate",
            f"[{win_rate_color}]{self.metrics.win_rate:.1%}[/{win_rate_color}]"
        )
        table.add_row(
            "Total P&L",
            f"[{pnl_color}]${self.metrics.total_pnl:.2f}[/{pnl_color}]"
        )
        table.add_row("Avg Trade", f"${self.metrics.average_trade:.2f}")
        table.add_row("Best Trade", f"[green]${self.metrics.best_trade:.2f}[/green]")
        table.add_row("Worst Trade", f"[red]${self.metrics.worst_trade:.2f}[/red]")
        table.add_row("Total Fees", f"${self.metrics.total_fees_paid:.2f}")

        return table
