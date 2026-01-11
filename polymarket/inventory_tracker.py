# Inventory Tracker for position and skew management
import logging
from datetime import datetime
from typing import Optional

from models import (
    MarketPosition, Position, Outcome, Fill, Side
)

logger = logging.getLogger(__name__)


class InventoryTracker:
    """
    Tracks positions across all markets and calculates inventory skew.
    """
    
    def __init__(self, skew_threshold: float = 1.2):
        self.positions: dict[str, MarketPosition] = {}
        self.skew_threshold = skew_threshold
    
    def get_or_create_position(
        self,
        condition_id: str,
        yes_token_id: str,
        no_token_id: str
    ) -> MarketPosition:
        """Get existing position or create new one."""
        if condition_id not in self.positions:
            self.positions[condition_id] = MarketPosition(
                condition_id=condition_id,
                yes_position=Position(token_id=yes_token_id, outcome=Outcome.YES),
                no_position=Position(token_id=no_token_id, outcome=Outcome.NO)
            )
        return self.positions[condition_id]
    
    def get_position(self, condition_id: str) -> Optional[MarketPosition]:
        """Get position for a market."""
        return self.positions.get(condition_id)
    
    def record_fill(self, condition_id: str, fill: Fill) -> None:
        """Record a fill and update position."""
        position = self.positions.get(condition_id)
        if not position:
            logger.warning(f"No position found for {condition_id}, cannot record fill")
            return
        
        if fill.side != Side.BUY:
            logger.warning("Only BUY fills should update inventory (we're accumulating)")
            return
        
        if fill.outcome == Outcome.YES:
            position.yes_position.add_fill(fill.size, fill.price)
            logger.info(
                f"YES fill: {fill.size}@{fill.price:.4f} | "
                f"New avg: {position.yes_position.avg_cost:.4f} | "
                f"Total qty: {position.yes_position.quantity:.2f}"
            )
        else:
            position.no_position.add_fill(fill.size, fill.price)
            logger.info(
                f"NO fill: {fill.size}@{fill.price:.4f} | "
                f"New avg: {position.no_position.avg_cost:.4f} | "
                f"Total qty: {position.no_position.quantity:.2f}"
            )
        
        self._log_skew(position)
    
    def get_skew_ratio(self, condition_id: str) -> float:
        """Get YES/NO quantity ratio for a market."""
        position = self.positions.get(condition_id)
        return position.skew_ratio if position else 1.0
    
    def is_yes_heavy(self, condition_id: str) -> bool:
        """Check if position is skewed towards YES."""
        ratio = self.get_skew_ratio(condition_id)
        return ratio > self.skew_threshold
    
    def is_no_heavy(self, condition_id: str) -> bool:
        """Check if position is skewed towards NO."""
        position = self.positions.get(condition_id)
        if not position:
            return False
        return position.inverse_skew_ratio > self.skew_threshold
    
    def get_adjustment_direction(self, condition_id: str) -> tuple[int, int]:
        """
        Get bid adjustment for YES and NO based on skew.
        Returns (yes_adjustment, no_adjustment) in ticks.
        
        If YES heavy: lower YES bid (-1), raise NO bid (+1 to level 1)
        If NO heavy: lower NO bid (-1), raise YES bid (+1 to level 1)
        If balanced: no adjustment (0, 0)
        """
        if self.is_yes_heavy(condition_id):
            return (-1, 1)  # Discourage YES, encourage NO
        elif self.is_no_heavy(condition_id):
            return (1, -1)  # Encourage YES, discourage NO
        return (0, 0)
    
    def get_yes_quantity(self, condition_id: str) -> float:
        """Get total YES quantity."""
        position = self.positions.get(condition_id)
        return position.yes_position.quantity if position else 0.0
    
    def get_no_quantity(self, condition_id: str) -> float:
        """Get total NO quantity."""
        position = self.positions.get(condition_id)
        return position.no_position.quantity if position else 0.0
    
    def get_yes_avg_cost(self, condition_id: str) -> float:
        """Get average cost of YES position."""
        position = self.positions.get(condition_id)
        return position.yes_position.avg_cost if position else 0.0
    
    def get_no_avg_cost(self, condition_id: str) -> float:
        """Get average cost of NO position."""
        position = self.positions.get(condition_id)
        return position.no_position.avg_cost if position else 0.0
    
    def get_box_cost(self, condition_id: str) -> float:
        """Get current cost of 1 YES + 1 NO at average costs."""
        position = self.positions.get(condition_id)
        return position.box_cost if position else 0.0
    
    def get_total_spent(self, condition_id: str) -> float:
        """Get total USDC spent on a market."""
        position = self.positions.get(condition_id)
        return position.total_usdc_spent if position else 0.0
    
    def get_all_spent(self) -> float:
        """Get total USDC spent across all markets."""
        return sum(p.total_usdc_spent for p in self.positions.values())
    
    def _log_skew(self, position: MarketPosition) -> None:
        """Log skew information."""
        yes_qty = position.yes_position.quantity
        no_qty = position.no_position.quantity
        ratio = position.skew_ratio
        box = position.box_cost
        
        status = "BALANCED"
        if ratio > self.skew_threshold:
            status = "YES_HEAVY"
        elif ratio < 1 / self.skew_threshold:
            status = "NO_HEAVY"
        
        logger.debug(
            f"Skew: YES={yes_qty:.2f} NO={no_qty:.2f} | "
            f"Ratio={ratio:.3f} | Box={box:.4f} | {status}"
        )
    
    def load_from_positions(self, positions: dict[str, MarketPosition]) -> None:
        """Load positions from persisted state."""
        self.positions = positions
        logger.info(f"Loaded {len(positions)} positions from state")
    
    def export_positions(self) -> dict[str, MarketPosition]:
        """Export positions for persistence."""
        return self.positions.copy()
