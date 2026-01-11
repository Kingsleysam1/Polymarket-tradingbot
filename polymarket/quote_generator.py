# Quote Generator with inventory skew logic
import logging
from typing import Optional

from models import Quote, Side, Outcome, OrderBook
from config import TradingConfig

logger = logging.getLogger(__name__)


class QuoteGenerator:
    """
    Generates quotes with inventory skew adjustments.
    
    Strategy:
    - Place bids at best_bid - 1 tick (passive placement)
    - If YES_qty > 1.2 * NO_qty: lower YES bid, raise NO bid to level 1
    - If NO_qty > 1.2 * YES_qty: lower NO bid, raise YES bid to level 1
    - All orders are post_only=True
    - Respect breakeven constraints
    """
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.tick_size = config.tick_size
        self.base_size = config.base_quote_size
        self.skew_threshold = config.skew_threshold
    
    def generate_quotes(
        self,
        condition_id: str,
        yes_token_id: str,
        no_token_id: str,
        yes_orderbook: Optional[OrderBook],
        no_orderbook: Optional[OrderBook],
        yes_qty: float,
        no_qty: float,
        max_yes_bid: float,
        max_no_bid: float
    ) -> list[Quote]:
        """
        Generate bid quotes for both YES and NO tokens.
        
        Returns list of Quote objects ready for batch submission.
        """
        quotes = []
        
        # Calculate skew ratio
        skew_ratio = self._get_skew_ratio(yes_qty, no_qty)
        yes_adj, no_adj = self._get_skew_adjustments(skew_ratio)
        
        # Generate YES quote
        yes_quote = self._generate_single_quote(
            token_id=yes_token_id,
            outcome=Outcome.YES,
            orderbook=yes_orderbook,
            tick_adjustment=yes_adj,
            max_price=max_yes_bid
        )
        if yes_quote:
            quotes.append(yes_quote)
        
        # Generate NO quote
        no_quote = self._generate_single_quote(
            token_id=no_token_id,
            outcome=Outcome.NO,
            orderbook=no_orderbook,
            tick_adjustment=no_adj,
            max_price=max_no_bid
        )
        if no_quote:
            quotes.append(no_quote)
        
        self._log_quotes(quotes, skew_ratio, yes_adj, no_adj)
        
        return quotes
    
    def _generate_single_quote(
        self,
        token_id: str,
        outcome: Outcome,
        orderbook: Optional[OrderBook],
        tick_adjustment: int,
        max_price: float
    ) -> Optional[Quote]:
        """Generate a single bid quote."""
        if not orderbook:
            logger.debug(f"No orderbook for {outcome.value}, skipping quote")
            return None
        
        best_bid = orderbook.best_bid
        if best_bid is None:
            logger.debug(f"No best bid for {outcome.value}, skipping quote")
            return None
        
        # Calculate quote price: best_bid - 1 tick (passive) + adjustment
        # Base: place 1 tick behind best bid
        # Adjustment: +1 means move to level 1 (best bid), -1 means move further back
        base_price = best_bid - self.tick_size
        
        if tick_adjustment > 0:
            # Move to level 1 (best bid)
            quote_price = best_bid
        elif tick_adjustment < 0:
            # Move further back
            quote_price = base_price + (tick_adjustment * self.tick_size)
        else:
            # Standard: 1 tick behind
            quote_price = base_price
        
        # Round to tick size
        quote_price = round(quote_price / self.tick_size) * self.tick_size
        
        # Ensure we don't exceed max price (breakeven constraint)
        if quote_price > max_price:
            logger.debug(
                f"Quote price {quote_price:.4f} exceeds max {max_price:.4f} "
                f"for {outcome.value}, clamping"
            )
            quote_price = round(max_price / self.tick_size) * self.tick_size
        
        # Validate price range
        if quote_price < self.config.min_price or quote_price > self.config.max_price:
            logger.debug(
                f"Quote price {quote_price:.4f} outside valid range "
                f"[{self.config.min_price}, {self.config.max_price}]"
            )
            return None
        
        if quote_price <= 0:
            logger.debug(f"Invalid quote price {quote_price:.4f}")
            return None
        
        return Quote(
            token_id=token_id,
            outcome=outcome,
            side=Side.BUY,
            price=round(quote_price, 4),
            size=self.base_size
        )
    
    def _get_skew_ratio(self, yes_qty: float, no_qty: float) -> float:
        """Calculate YES/NO quantity ratio."""
        if no_qty == 0:
            return float("inf") if yes_qty > 0 else 1.0
        return yes_qty / no_qty
    
    def _get_skew_adjustments(self, skew_ratio: float) -> tuple[int, int]:
        """
        Get tick adjustments based on skew.
        
        Returns (yes_adjustment, no_adjustment).
        - Positive adjustment means move to level 1 (more aggressive)
        - Negative adjustment means move further back (less aggressive)
        """
        if skew_ratio > self.skew_threshold:
            # YES heavy: discourage YES, encourage NO
            return (-1, 1)
        elif skew_ratio < (1 / self.skew_threshold):
            # NO heavy: encourage YES, discourage NO
            return (1, -1)
        else:
            # Balanced
            return (0, 0)
    
    def _log_quotes(
        self,
        quotes: list[Quote],
        skew_ratio: float,
        yes_adj: int,
        no_adj: int
    ) -> None:
        """Log generated quotes."""
        status = "BALANCED"
        if yes_adj < 0:
            status = "YES_HEAVY"
        elif no_adj < 0:
            status = "NO_HEAVY"
        
        for quote in quotes:
            logger.debug(
                f"Quote: {quote.outcome.value} BID {quote.size}@{quote.price:.4f} | "
                f"Skew: {skew_ratio:.3f} ({status})"
            )
    
    def adjust_size_for_position_limit(
        self,
        quote: Quote,
        current_position_value: float,
        max_position: float
    ) -> Optional[Quote]:
        """
        Reduce quote size if approaching position limit.
        Returns None if limit exceeded.
        """
        remaining_capacity = max_position - current_position_value
        
        if remaining_capacity <= 0:
            logger.warning(
                f"Position limit reached for {quote.outcome.value}, skipping quote"
            )
            return None
        
        quote_value = quote.price * quote.size
        
        if quote_value > remaining_capacity:
            # Reduce size to fit
            new_size = remaining_capacity / quote.price
            new_size = round(new_size, 2)  # Round to 2 decimal places
            
            if new_size < 0.1:  # Minimum viable size
                return None
            
            logger.debug(
                f"Reduced {quote.outcome.value} size from {quote.size} to {new_size} "
                f"due to position limit"
            )
            quote.size = new_size
        
        return quote


class BatchQuoteBuilder:
    """
    Builds batch of quotes across multiple markets.
    """
    
    def __init__(self, max_batch_size: int = 10):
        self.max_batch_size = max_batch_size
        self.quotes: list[Quote] = []
    
    def add_quotes(self, quotes: list[Quote]) -> None:
        """Add quotes to the batch."""
        for quote in quotes:
            if len(self.quotes) < self.max_batch_size:
                self.quotes.append(quote)
    
    def build(self) -> list[Quote]:
        """Return and clear the batch."""
        batch = self.quotes
        self.quotes = []
        return batch
    
    def is_full(self) -> bool:
        """Check if batch is full."""
        return len(self.quotes) >= self.max_batch_size
    
    def is_empty(self) -> bool:
        """Check if batch is empty."""
        return len(self.quotes) == 0
    
    def size(self) -> int:
        """Get current batch size."""
        return len(self.quotes)
