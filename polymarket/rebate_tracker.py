# Rebate Tracker for estimating daily USDC maker rebates
import logging
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DailyRebateStats:
    """Daily rebate statistics."""
    date: date
    maker_volume: float = 0.0
    estimated_rebate: float = 0.0
    fill_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "maker_volume": self.maker_volume,
            "estimated_rebate": self.estimated_rebate,
            "fill_count": self.fill_count
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DailyRebateStats":
        return cls(
            date=date.fromisoformat(data["date"]),
            maker_volume=data["maker_volume"],
            estimated_rebate=data["estimated_rebate"],
            fill_count=data["fill_count"]
        )


class RebateTracker:
    """
    Tracks and estimates daily USDC maker rebates.
    
    Polymarket typically offers rebates to makers based on their trading volume.
    The exact rebate schedule may vary; this uses a configurable rate.
    """
    
    def __init__(self, rebate_rate_bps: float = 10.0):
        """
        Initialize rebate tracker.
        
        Args:
            rebate_rate_bps: Rebate rate in basis points (100 bps = 1%)
                            Default 10 bps = 0.1% of maker volume
        """
        self.rebate_rate = rebate_rate_bps / 10000  # Convert bps to decimal
        self.daily_stats: dict[date, DailyRebateStats] = {}
        self.total_maker_volume: float = 0.0
        self.total_estimated_rebates: float = 0.0
    
    def record_fill(self, fill_amount: float, is_maker: bool = True) -> None:
        """
        Record a fill and estimate rebate.
        
        Args:
            fill_amount: USDC notional value of the fill
            is_maker: True if we were the maker (we should always be maker)
        """
        if not is_maker:
            logger.debug("Taker fill - no rebate")
            return
        
        today = date.today()
        
        if today not in self.daily_stats:
            self.daily_stats[today] = DailyRebateStats(date=today)
        
        stats = self.daily_stats[today]
        rebate_amount = fill_amount * self.rebate_rate
        
        stats.maker_volume += fill_amount
        stats.estimated_rebate += rebate_amount
        stats.fill_count += 1
        
        self.total_maker_volume += fill_amount
        self.total_estimated_rebates += rebate_amount
        
        logger.debug(
            f"Fill recorded: ${fill_amount:.2f} | "
            f"Rebate est: ${rebate_amount:.4f} | "
            f"Today total: ${stats.estimated_rebate:.4f}"
        )
    
    def get_today_stats(self) -> DailyRebateStats:
        """Get today's rebate statistics."""
        today = date.today()
        if today not in self.daily_stats:
            return DailyRebateStats(date=today)
        return self.daily_stats[today]
    
    def get_stats_for_date(self, target_date: date) -> Optional[DailyRebateStats]:
        """Get rebate statistics for a specific date."""
        return self.daily_stats.get(target_date)
    
    def get_total_volume(self) -> float:
        """Get total maker volume across all days."""
        return self.total_maker_volume
    
    def get_total_rebates(self) -> float:
        """Get total estimated rebates across all days."""
        return self.total_estimated_rebates
    
    def get_daily_summary(self) -> list[dict]:
        """Get summary of all daily stats."""
        return [
            stats.to_dict()
            for stats in sorted(self.daily_stats.values(), key=lambda x: x.date)
        ]
    
    def print_summary(self) -> str:
        """Generate printable summary of rebate statistics."""
        lines = [
            "=" * 50,
            "MAKER REBATE SUMMARY",
            "=" * 50,
            f"Total Maker Volume: ${self.total_maker_volume:,.2f}",
            f"Estimated Total Rebates: ${self.total_estimated_rebates:.4f}",
            f"Rebate Rate: {self.rebate_rate * 100:.2f}%",
            "-" * 50,
            "Daily Breakdown:",
        ]
        
        for stats in sorted(self.daily_stats.values(), key=lambda x: x.date):
            lines.append(
                f"  {stats.date}: ${stats.maker_volume:,.2f} volume, "
                f"${stats.estimated_rebate:.4f} rebate, "
                f"{stats.fill_count} fills"
            )
        
        lines.append("=" * 50)
        return "\n".join(lines)
    
    def export_state(self) -> dict:
        """Export state for persistence."""
        return {
            "rebate_rate_bps": self.rebate_rate * 10000,
            "total_maker_volume": self.total_maker_volume,
            "total_estimated_rebates": self.total_estimated_rebates,
            "daily_stats": {
                d.isoformat(): s.to_dict() 
                for d, s in self.daily_stats.items()
            }
        }
    
    def load_state(self, state: dict) -> None:
        """Load state from persistence."""
        self.rebate_rate = state.get("rebate_rate_bps", 10.0) / 10000
        self.total_maker_volume = state.get("total_maker_volume", 0.0)
        self.total_estimated_rebates = state.get("total_estimated_rebates", 0.0)
        
        for date_str, stats_dict in state.get("daily_stats", {}).items():
            d = date.fromisoformat(date_str)
            self.daily_stats[d] = DailyRebateStats.from_dict(stats_dict)
        
        logger.info(
            f"Loaded rebate state: ${self.total_maker_volume:.2f} volume, "
            f"${self.total_estimated_rebates:.4f} rebates"
        )
