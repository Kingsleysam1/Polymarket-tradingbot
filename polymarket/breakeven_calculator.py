# Breakeven Box Calculator
import logging
from typing import Optional

from models import Outcome

logger = logging.getLogger(__name__)


class BreakevenCalculator:
    """
    Calculates breakeven constraints for market making.
    
    Goal: Ensure total cost of 1 YES + 1 NO < $0.99 (inclusive of fees).
    
    Formula for new YES bid:
        (TotalSpend_YES + NewPrice × Qty) / (TotalQty_YES + Qty) + AvgCost_NO < 0.99
    
    Rearranged to find max allowable price:
        NewPrice < ((0.99 - AvgCost_NO) × (TotalQty_YES + Qty) - TotalSpend_YES) / Qty
    """
    
    def __init__(
        self,
        breakeven_target: float = 0.99,
        safety_margin: float = 0.005
    ):
        self.breakeven_target = breakeven_target
        self.safety_margin = safety_margin
        self.effective_target = breakeven_target - safety_margin
    
    def calculate_max_bid(
        self,
        outcome: Outcome,
        total_spend_yes: float,
        total_qty_yes: float,
        avg_cost_no: float,
        total_spend_no: float,
        total_qty_no: float,
        avg_cost_yes: float,
        new_qty: float
    ) -> float:
        """
        Calculate maximum allowable bid price for a given quantity.
        
        Args:
            outcome: Which outcome we're bidding on (YES or NO)
            total_spend_yes: Total USDC spent on YES so far
            total_qty_yes: Total YES shares owned
            avg_cost_no: Current average cost of NO shares
            total_spend_no: Total USDC spent on NO so far
            total_qty_no: Total NO shares owned
            avg_cost_yes: Current average cost of YES shares
            new_qty: Quantity we want to bid for
        
        Returns:
            Maximum bid price that maintains breakeven constraint.
        """
        if new_qty <= 0:
            return 0.0
        
        if outcome == Outcome.YES:
            return self._calc_max_yes_bid(
                total_spend_yes, total_qty_yes, avg_cost_no, new_qty
            )
        else:
            return self._calc_max_no_bid(
                total_spend_no, total_qty_no, avg_cost_yes, new_qty
            )
    
    def _calc_max_yes_bid(
        self,
        total_spend_yes: float,
        total_qty_yes: float,
        avg_cost_no: float,
        new_qty: float
    ) -> float:
        """
        Calculate max YES bid.
        
        new_avg_yes = (TotalSpend_YES + NewPrice × Qty) / (TotalQty_YES + Qty)
        Constraint: new_avg_yes + avg_cost_no < effective_target
        
        Solving for NewPrice:
        NewPrice < ((effective_target - avg_cost_no) × (TotalQty_YES + Qty) - TotalSpend_YES) / Qty
        """
        # Max average YES cost we can have
        max_avg_yes = self.effective_target - avg_cost_no
        
        if max_avg_yes <= 0:
            logger.warning(
                f"No room for YES bid: avg_cost_no={avg_cost_no:.4f} "
                f">= target={self.effective_target:.4f}"
            )
            return 0.0
        
        # Calculate max price
        new_total_qty = total_qty_yes + new_qty
        max_total_spend = max_avg_yes * new_total_qty
        max_new_spend = max_total_spend - total_spend_yes
        max_price = max_new_spend / new_qty
        
        # Clamp to valid range [0.01, 0.99]
        max_price = max(0.01, min(0.99, max_price))
        
        logger.debug(
            f"Max YES bid: {max_price:.4f} | "
            f"Current spend: {total_spend_yes:.2f}, qty: {total_qty_yes:.2f} | "
            f"NO avg: {avg_cost_no:.4f}"
        )
        
        return max_price
    
    def _calc_max_no_bid(
        self,
        total_spend_no: float,
        total_qty_no: float,
        avg_cost_yes: float,
        new_qty: float
    ) -> float:
        """
        Calculate max NO bid.
        
        Constraint: avg_cost_yes + new_avg_no < effective_target
        """
        # Max average NO cost we can have
        max_avg_no = self.effective_target - avg_cost_yes
        
        if max_avg_no <= 0:
            logger.warning(
                f"No room for NO bid: avg_cost_yes={avg_cost_yes:.4f} "
                f">= target={self.effective_target:.4f}"
            )
            return 0.0
        
        # Calculate max price
        new_total_qty = total_qty_no + new_qty
        max_total_spend = max_avg_no * new_total_qty
        max_new_spend = max_total_spend - total_spend_no
        max_price = max_new_spend / new_qty
        
        # Clamp to valid range [0.01, 0.99]
        max_price = max(0.01, min(0.99, max_price))
        
        logger.debug(
            f"Max NO bid: {max_price:.4f} | "
            f"Current spend: {total_spend_no:.2f}, qty: {total_qty_no:.2f} | "
            f"YES avg: {avg_cost_yes:.4f}"
        )
        
        return max_price
    
    def is_bid_valid(
        self,
        outcome: Outcome,
        bid_price: float,
        new_qty: float,
        total_spend_yes: float,
        total_qty_yes: float,
        avg_cost_no: float,
        total_spend_no: float,
        total_qty_no: float,
        avg_cost_yes: float
    ) -> bool:
        """
        Check if a bid would maintain the breakeven constraint.
        """
        max_bid = self.calculate_max_bid(
            outcome=outcome,
            total_spend_yes=total_spend_yes,
            total_qty_yes=total_qty_yes,
            avg_cost_no=avg_cost_no,
            total_spend_no=total_spend_no,
            total_qty_no=total_qty_no,
            avg_cost_yes=avg_cost_yes,
            new_qty=new_qty
        )
        
        is_valid = bid_price <= max_bid
        
        if not is_valid:
            logger.warning(
                f"Bid {outcome.value} {new_qty}@{bid_price:.4f} exceeds max {max_bid:.4f}"
            )
        
        return is_valid
    
    def calculate_projected_box_cost(
        self,
        outcome: Outcome,
        bid_price: float,
        new_qty: float,
        total_spend_yes: float,
        total_qty_yes: float,
        total_spend_no: float,
        total_qty_no: float
    ) -> float:
        """
        Calculate what the box cost would be after a fill at the given price.
        """
        if outcome == Outcome.YES:
            new_spend_yes = total_spend_yes + (bid_price * new_qty)
            new_qty_yes = total_qty_yes + new_qty
            new_avg_yes = new_spend_yes / new_qty_yes if new_qty_yes > 0 else 0
            new_avg_no = total_spend_no / total_qty_no if total_qty_no > 0 else 0
        else:
            new_spend_no = total_spend_no + (bid_price * new_qty)
            new_qty_no = total_qty_no + new_qty
            new_avg_no = new_spend_no / new_qty_no if new_qty_no > 0 else 0
            new_avg_yes = total_spend_yes / total_qty_yes if total_qty_yes > 0 else 0
        
        return new_avg_yes + new_avg_no
    
    def get_profit_margin(
        self,
        avg_cost_yes: float,
        avg_cost_no: float
    ) -> float:
        """
        Calculate profit margin on the current box.
        
        If avg_cost_yes + avg_cost_no < 1.0, we profit when market resolves.
        Profit = 1.0 - (avg_cost_yes + avg_cost_no)
        """
        box_cost = avg_cost_yes + avg_cost_no
        return 1.0 - box_cost
