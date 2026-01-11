# Unit tests for Inventory Skew Logic
import pytest
from inventory_tracker import InventoryTracker
from models import Position, MarketPosition, Outcome, Fill, Side


class TestInventoryTracker:
    """Tests for the inventory tracker."""
    
    def setup_method(self):
        """Setup tracker with 1.2 skew threshold."""
        self.tracker = InventoryTracker(skew_threshold=1.2)
    
    def test_create_position(self):
        """Can create new position."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        assert position.condition_id == "test_market"
        assert position.yes_position.quantity == 0.0
        assert position.no_position.quantity == 0.0
    
    def test_record_yes_fill(self):
        """Records YES fill correctly."""
        self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        fill = Fill(
            order_id="order1",
            token_id="yes_token",
            outcome=Outcome.YES,
            side=Side.BUY,
            price=0.40,
            size=10.0
        )
        
        self.tracker.record_fill("test_market", fill)
        
        assert self.tracker.get_yes_quantity("test_market") == 10.0
        assert self.tracker.get_yes_avg_cost("test_market") == pytest.approx(0.40)
    
    def test_record_no_fill(self):
        """Records NO fill correctly."""
        self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        fill = Fill(
            order_id="order1",
            token_id="no_token",
            outcome=Outcome.NO,
            side=Side.BUY,
            price=0.55,
            size=5.0
        )
        
        self.tracker.record_fill("test_market", fill)
        
        assert self.tracker.get_no_quantity("test_market") == 5.0
        assert self.tracker.get_no_avg_cost("test_market") == pytest.approx(0.55)
    
    def test_skew_ratio_balanced(self):
        """Skew ratio is 1.0 when balanced."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        # Add equal positions
        position.yes_position.add_fill(10.0, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        ratio = self.tracker.get_skew_ratio("test_market")
        assert ratio == pytest.approx(1.0)
    
    def test_skew_ratio_yes_heavy(self):
        """Skew ratio > 1.2 when YES heavy."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(15.0, 0.40)  # 15 YES
        position.no_position.add_fill(10.0, 0.50)   # 10 NO
        
        ratio = self.tracker.get_skew_ratio("test_market")
        assert ratio == pytest.approx(1.5)
        assert self.tracker.is_yes_heavy("test_market") is True
        assert self.tracker.is_no_heavy("test_market") is False
    
    def test_skew_ratio_no_heavy(self):
        """Skew ratio < 0.83 when NO heavy."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(10.0, 0.40)  # 10 YES
        position.no_position.add_fill(15.0, 0.50)   # 15 NO
        
        ratio = self.tracker.get_skew_ratio("test_market")
        assert ratio == pytest.approx(0.667, abs=0.01)
        assert self.tracker.is_no_heavy("test_market") is True
        assert self.tracker.is_yes_heavy("test_market") is False
    
    def test_adjustment_when_yes_heavy(self):
        """Adjustments correct when YES heavy."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(15.0, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        yes_adj, no_adj = self.tracker.get_adjustment_direction("test_market")
        
        # Should lower YES bid, raise NO bid
        assert yes_adj == -1
        assert no_adj == 1
    
    def test_adjustment_when_no_heavy(self):
        """Adjustments correct when NO heavy."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(10.0, 0.40)
        position.no_position.add_fill(15.0, 0.50)
        
        yes_adj, no_adj = self.tracker.get_adjustment_direction("test_market")
        
        # Should raise YES bid, lower NO bid
        assert yes_adj == 1
        assert no_adj == -1
    
    def test_adjustment_when_balanced(self):
        """No adjustments when balanced."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(10.0, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        yes_adj, no_adj = self.tracker.get_adjustment_direction("test_market")
        
        assert yes_adj == 0
        assert no_adj == 0
    
    def test_box_cost(self):
        """Box cost calculation correct."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(10.0, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        box = self.tracker.get_box_cost("test_market")
        assert box == pytest.approx(0.90)
    
    def test_total_spent(self):
        """Total spent calculation correct."""
        position = self.tracker.get_or_create_position(
            condition_id="test_market",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        position.yes_position.add_fill(10.0, 0.40)  # $4.00
        position.no_position.add_fill(10.0, 0.50)   # $5.00
        
        spent = self.tracker.get_total_spent("test_market")
        assert spent == pytest.approx(9.0)


class TestSkewThresholds:
    """Test different skew thresholds."""
    
    def test_higher_threshold(self):
        """Higher threshold requires more imbalance."""
        tracker = InventoryTracker(skew_threshold=1.5)
        
        position = tracker.get_or_create_position(
            condition_id="test",
            yes_token_id="yes",
            no_token_id="no"
        )
        
        # 1.4x skew - not yet YES heavy with 1.5 threshold
        position.yes_position.add_fill(14.0, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        assert tracker.is_yes_heavy("test") is False
        
        # 1.6x skew - now YES heavy
        position.yes_position.add_fill(2.0, 0.40)
        
        assert tracker.is_yes_heavy("test") is True
    
    def test_lower_threshold(self):
        """Lower threshold triggers sooner."""
        tracker = InventoryTracker(skew_threshold=1.1)
        
        position = tracker.get_or_create_position(
            condition_id="test",
            yes_token_id="yes",
            no_token_id="no"
        )
        
        # 1.15x skew - YES heavy with 1.1 threshold
        position.yes_position.add_fill(11.5, 0.40)
        position.no_position.add_fill(10.0, 0.50)
        
        assert tracker.is_yes_heavy("test") is True


class TestEdgeCases:
    """Edge case tests for inventory tracker."""
    
    def test_skew_ratio_no_position(self):
        """Skew ratio is 1.0 with no position."""
        tracker = InventoryTracker()
        ratio = tracker.get_skew_ratio("nonexistent")
        assert ratio == 1.0
    
    def test_skew_ratio_only_yes(self):
        """Skew ratio is inf with only YES."""
        tracker = InventoryTracker()
        position = tracker.get_or_create_position(
            condition_id="test",
            yes_token_id="yes",
            no_token_id="no"
        )
        
        position.yes_position.add_fill(10.0, 0.40)
        
        ratio = tracker.get_skew_ratio("test")
        assert ratio == float("inf")
    
    def test_skew_ratio_only_no(self):
        """Skew ratio is 0 with only NO."""
        tracker = InventoryTracker()
        position = tracker.get_or_create_position(
            condition_id="test",
            yes_token_id="yes",
            no_token_id="no"
        )
        
        position.no_position.add_fill(10.0, 0.50)
        
        ratio = tracker.get_skew_ratio("test")
        assert ratio == 0.0
