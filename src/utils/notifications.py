"""
Notification manager for alerts and updates
"""
import asyncio
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import aiohttp

from src.models import Position, ArbitrageOpportunity
from src.config import config
from src.utils.logger import bot_logger


class NotificationManager:
    """Manages notifications and alerts"""
    
    def __init__(self):
        """Initialize notification manager"""
        self.telegram_enabled = config.ENABLE_TELEGRAM_ALERTS
        self.telegram_token = config.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = config.TELEGRAM_CHAT_ID
        
        if self.telegram_enabled:
            if not self.telegram_token or not self.telegram_chat_id:
                bot_logger.warning("Telegram alerts enabled but credentials missing")
                self.telegram_enabled = False
            else:
                bot_logger.info("Telegram notifications enabled")
    
    async def send_telegram_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message via Telegram
        
        Args:
            message: Message text
            parse_mode: Telegram parse mode (Markdown or HTML)
        
        Returns:
            Success status
        """
        if not self.telegram_enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        bot_logger.debug("Telegram message sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        bot_logger.error(f"Failed to send Telegram message: {error_text}")
                        return False
                        
        except Exception as e:
            bot_logger.error(f"Error sending Telegram message: {e}")
            return False
    
    async def send_startup_alert(self):
        """Send bot startup notification"""
        message = (
            "🤖 *Polymarket Arbitrage Bot Started*\n\n"
            f"⏰ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"💰 Mode: {'Live Trading' if config.ENVIRONMENT == 'production' else 'Paper Trading'}\n"
            f"📊 Max Position: ${config.MAX_POSITION_SIZE_USD}\n"
            f"🎯 Min Profit: ${config.MIN_PROFIT_THRESHOLD_USD}\n"
            f"⚡ Max Concurrent: {config.MAX_CONCURRENT_POSITIONS}\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_opportunity_alert(self, opportunity: ArbitrageOpportunity):
        """Send notification about a profitable opportunity"""
        message = (
            "💡 *New Arbitrage Opportunity*\n\n"
            f"🪙 Asset: {opportunity.polymarket.asset}\n"
            f"📈 Polymarket: {opportunity.polymarket_side.value} @ {opportunity.polymarket_price:.4f}\n"
            f"🔄 Hedge: {opportunity.hedge_side.value} @ ${opportunity.hedge_price:.2f}\n"
            f"💵 Expected Profit: ${opportunity.expected_profit_usd:.2f} "
            f"({opportunity.expected_profit_percentage:.1f}%)\n"
            f"📊 Probability: {opportunity.probability_of_profit:.1%}\n"
            f"⏱️ Expires: {opportunity.expires_at.strftime('%H:%M')} UTC\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_trade_alert(self, position: Position):
        """Send notification about executed trade"""
        message = (
            "✅ *Trade Executed*\n\n"
            f"🆔 Position: `{position.position_id[:8]}`\n"
            f"🪙 Symbol: {position.hedge_symbol}\n"
            f"📈 Polymarket: {position.polymarket_side.value} "
            f"{position.polymarket_quantity:.2f} @ {position.polymarket_entry_price:.4f}\n"
            f"🔄 Hedge: {position.hedge_side.value} "
            f"{position.hedge_quantity:.4f} @ ${position.hedge_entry_price:.2f}\n"
            f"🛑 Stop Loss: ${position.stop_loss_price:.2f}\n"
            f"🎯 Take Profit: ${position.take_profit_price:.2f}\n"
            f"⚠️ Max Risk: ${position.max_loss_usd:.2f}\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_position_closed_alert(self, position: Position, reason: str):
        """Send notification when position is closed"""
        pnl_emoji = "🟢" if position.net_pnl >= 0 else "🔴"
        pnl_text = f"+${position.net_pnl:.2f}" if position.net_pnl >= 0 else f"-${abs(position.net_pnl):.2f}"
        
        message = (
            f"{pnl_emoji} *Position Closed*\n\n"
            f"🆔 Position: `{position.position_id[:8]}`\n"
            f"📊 Reason: {reason}\n"
            f"💰 Net P&L: {pnl_text}\n"
            f"⏱️ Duration: {position.duration_hours:.1f} hours\n"
            f"💸 Fees Paid: ${position.total_fees:.2f}\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_daily_summary(self, metrics: dict):
        """Send daily performance summary"""
        message = (
            "📊 *Daily Performance Summary*\n\n"
            f"📅 Date: {datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📈 Total Trades: {metrics.get('total_trades', 0)}\n"
            f"✅ Winning: {metrics.get('winning_trades', 0)}\n"
            f"❌ Losing: {metrics.get('losing_trades', 0)}\n"
            f"📊 Win Rate: {metrics.get('win_rate', 0):.1%}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"💰 Daily P&L: ${metrics.get('daily_pnl', 0):.2f}\n"
            f"📈 Best Trade: ${metrics.get('best_trade', 0):.2f}\n"
            f"📉 Worst Trade: ${metrics.get('worst_trade', 0):.2f}\n"
            f"💵 Total Volume: ${metrics.get('total_volume', 0):.2f}\n"
            f"💸 Fees Paid: ${metrics.get('total_fees', 0):.2f}\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_error_alert(self, error_message: str, critical: bool = False):
        """Send error notification"""
        emoji = "🚨" if critical else "⚠️"
        level = "CRITICAL ERROR" if critical else "ERROR"
        
        message = (
            f"{emoji} *{level}*\n\n"
            f"❌ Error: {error_message}\n"
            f"⏰ Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC\n"
        )
        
        await self.send_telegram_message(message)
    
    async def send_balance_alert(self, balances: dict):
        """Send low balance alert"""
        total = sum(balances.values())
        
        message = (
            "⚠️ *Low Balance Warning*\n\n"
            f"💰 Total Balance: ${total:.2f}\n"
        )
        
        for asset, balance in balances.items():
            message += f"• {asset}: ${balance:.2f}\n"
        
        message += "\n⚡ Please add funds to continue trading"
        
        await self.send_telegram_message(message)
    
    async def send_shutdown_alert(self, final_metrics: dict):
        """Send bot shutdown notification"""
        message = (
            "🛑 *Bot Shutdown*\n\n"
            f"⏰ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 Final Statistics:\n"
            f"• Total Trades: {final_metrics.get('total_trades', 0)}\n"
            f"• Total P&L: ${final_metrics.get('total_pnl', 0):.2f}\n"
            f"• Win Rate: {final_metrics.get('win_rate', 0):.1%}\n"
            f"• Active Positions: {final_metrics.get('active_positions', 0)}\n"
        )
        
        await self.send_telegram_message(message)
