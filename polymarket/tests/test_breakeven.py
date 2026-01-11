# Unit tests for Breakeven Calculator
import pytest
from breakeven_calculator import BreakevenCalculator
from models import Outcome


class TestBreakevenCalculator:
    """Tests for the breakeven box calculator."""
    
    def setup_method(self):
        """Setup calculator with target $0.99 and $0.005 safety margin."""
        self.calc = BreakevenCalculator(
            breakeven_target=0.99,
            safety_margin=0.005
        )
    
    def test_max_yes_bid_no_existing_position(self):
        """With no existing position, max bid should be near target."""
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.0,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0,
            new_qty=10.0
        )
        
        # Max bid should be effective_target (0.985) when no NO position
        assert max_bid == pytest.approx(0.985, abs=0.001)
    
    def test_max_yes_bid_with_no_position(self):
        """Max YES bid reduced when NO avg cost is high."""
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.50,  # Already have NO at $0.50 avg
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0,
            new_qty=10.0
        )
        
        # Max YES bid = 0.985 - 0.50 = 0.485
        assert max_bid == pytest.approx(0.485, abs=0.001)
    
    def test_max_no_bid_with_yes_position(self):
        """Max NO bid reduced when YES avg cost is high."""
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.NO,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.0,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.45,  # Already have YES at $0.45 avg
            new_qty=10.0
        )
        
        # Max NO bid = 0.985 - 0.45 = 0.535
        assert max_bid == pytest.approx(0.535, abs=0.001)
    
    def test_max_bid_with_existing_yes_position(self):
        """Max YES bid accounts for existing YES position."""
        # Already have 10 YES at avg $0.40
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=4.0,  # 10 * $0.40
            total_qty_yes=10.0,
            avg_cost_no=0.50,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.40,
            new_qty=5.0
        )
        
        # With NO avg at 0.50, max avg YES = 0.485
        # new_avg_yes = (4.0 + price * 5) / 15 <= 0.485
        # price <= (0.485 * 15 - 4.0) / 5 = (7.275 - 4.0) / 5 = 0.655
        assert max_bid == pytest.approx(0.655, abs=0.01)
    
    def test_no_room_for_bid(self):
        """Returns 0 when no room for bid."""
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.99,  # NO cost already at target
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0,
            new_qty=10.0
        )
        
        # No room left for YES
        assert max_bid == 0.0
    
    def test_is_bid_valid_under_limit(self):
        """Bid under max is valid."""
        is_valid = self.calc.is_bid_valid(
            outcome=Outcome.YES,
            bid_price=0.40,
            new_qty=10.0,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.50,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0
        )
        
        assert is_valid is True
    
    def test_is_bid_valid_over_limit(self):
        """Bid over max is invalid."""
        is_valid = self.calc.is_bid_valid(
            outcome=Outcome.YES,
            bid_price=0.60,  # Above max of 0.485
            new_qty=10.0,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.50,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0
        )
        
        assert is_valid is False
    
    def test_projected_box_cost(self):
        """Calculate projected box cost after fill."""
        projected = self.calc.calculate_projected_box_cost(
            outcome=Outcome.YES,
            bid_price=0.40,
            new_qty=10.0,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            total_spend_no=5.0,  # 10 NO at $0.50
            total_qty_no=10.0
        )
        
        # YES avg = 0.40, NO avg = 0.50
        assert projected == pytest.approx(0.90, abs=0.001)
    
    def test_profit_margin(self):
        """Calculate profit margin on box."""
        margin = self.calc.get_profit_margin(
            avg_cost_yes=0.40,
            avg_cost_no=0.50
        )
        
        # Box cost = 0.90, profit = 1.0 - 0.90 = 0.10
        assert margin == pytest.approx(0.10, abs=0.001)
    
    def test_profit_margin_at_breakeven(self):
        """No profit at breakeven."""
        margin = self.calc.get_profit_margin(
            avg_cost_yes=0.50,
            avg_cost_no=0.50
        )
        
        # Box cost = 1.0, no profit
        assert margin == pytest.approx(0.0, abs=0.001)
    
    def test_negative_margin_loss(self):
        """Negative margin when overpaying."""
        margin = self.calc.get_profit_margin(
            avg_cost_yes=0.60,
            avg_cost_no=0.50
        )
        
        # Box cost = 1.10, loss of $0.10
        assert margin == pytest.approx(-0.10, abs=0.001)


class TestBreakevenEdgeCases:
    """Edge case tests for breakeven calculator."""
    
    def setup_method(self):
        self.calc = BreakevenCalculator()
    
    def test_zero_quantity(self):
        """Zero quantity returns 0 max bid."""
        max_bid = self.calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.0,
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0,
            new_qty=0.0
        )
        
        assert max_bid == 0.0
    
    def test_price_clamped_to_valid_range(self):
        """Max bid is clamped to 0.01-0.99 range."""
        calc = BreakevenCalculator(breakeven_target=0.99, safety_margin=0.0)
        
        max_bid = calc.calculate_max_bid(
            outcome=Outcome.YES,
            total_spend_yes=0.0,
            total_qty_yes=0.0,
            avg_cost_no=0.0,  # Would allow 0.99
            total_spend_no=0.0,
            total_qty_no=0.0,
            avg_cost_yes=0.0,
            new_qty=10.0
        )
        
        assert max_bid <= 0.99
        assert max_bid >= 0.01
