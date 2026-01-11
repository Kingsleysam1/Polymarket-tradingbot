# Market Filter for dynamic target selection
import re
import logging
from typing import Optional

from models import MarketInfo

logger = logging.getLogger(__name__)


class MarketFilter:
    """
    Filters markets based on asset, timeframe, and price criteria.
    
    Target: 15m/1h BTC, ETH, SOL markets where price is between $0.20 and $0.80.
    """
    
    def __init__(
        self,
        target_assets: list[str],
        target_timeframes: list[str],
        min_price: float = 0.20,
        max_price: float = 0.80,
        min_liquidity: float = 100.0
    ):
        self.target_assets = [a.upper() for a in target_assets]
        self.target_timeframes = [t.lower() for t in target_timeframes]
        self.min_price = min_price
        self.max_price = max_price
        self.min_liquidity = min_liquidity
        
        # Build regex patterns for matching
        self._asset_pattern = self._build_asset_pattern()
        self._timeframe_pattern = self._build_timeframe_pattern()
    
    def _build_asset_pattern(self) -> re.Pattern:
        """Build regex pattern for matching target assets."""
        assets = "|".join(re.escape(a) for a in self.target_assets)
        return re.compile(rf"\b({assets})\b", re.IGNORECASE)
    
    def _build_timeframe_pattern(self) -> re.Pattern:
        """Build regex pattern for matching target timeframes."""
        # Match patterns like "15m", "1h", "15 min", "1 hour"
        timeframe_patterns = []
        for tf in self.target_timeframes:
            if tf.endswith("m"):
                mins = tf[:-1]
                timeframe_patterns.append(rf"{mins}\s*(?:m|min|minute)")
            elif tf.endswith("h"):
                hours = tf[:-1]
                timeframe_patterns.append(rf"{hours}\s*(?:h|hr|hour)")
        
        pattern = "|".join(timeframe_patterns)
        return re.compile(rf"({pattern})", re.IGNORECASE)
    
    def is_eligible(self, market: MarketInfo) -> bool:
        """
        Check if a market is eligible for trading.
        
        Criteria:
        1. Market question contains target asset (BTC, ETH, SOL)
        2. Market question contains target timeframe (15m, 1h)
        3. Both YES and NO prices are within [min_price, max_price]
        4. Market is active
        """
        if not market.active:
            logger.debug(f"Market {market.condition_id[:8]} inactive, skipping")
            return False
        
        # Check asset match
        if not self._matches_asset(market.question):
            return False
        
        # Check timeframe match
        if not self._matches_timeframe(market.question):
            return False
        
        # Check price range
        if not self._in_price_range(market):
            return False
        
        logger.debug(f"Market eligible: {market.question[:50]}...")
        return True
    
    def _matches_asset(self, question: str) -> bool:
        """Check if question contains a target asset."""
        return bool(self._asset_pattern.search(question))
    
    def _matches_timeframe(self, question: str) -> bool:
        """Check if question contains a target timeframe."""
        return bool(self._timeframe_pattern.search(question))
    
    def _in_price_range(self, market: MarketInfo) -> bool:
        """Check if market prices are in tradeable range."""
        in_range = market.is_in_price_range(self.min_price, self.max_price)
        if not in_range:
            logger.debug(
                f"Market {market.condition_id[:8]} prices out of range: "
                f"YES={market.yes_price:.4f}, NO={market.no_price:.4f}"
            )
        return in_range
    
    def filter_markets(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter list of markets to eligible ones."""
        eligible = [m for m in markets if self.is_eligible(m)]
        logger.info(f"Filtered {len(markets)} markets to {len(eligible)} eligible")
        return eligible
    
    def extract_asset(self, question: str) -> Optional[str]:
        """Extract the asset from market question."""
        match = self._asset_pattern.search(question)
        return match.group(1).upper() if match else None
    
    def extract_timeframe(self, question: str) -> Optional[str]:
        """Extract the timeframe from market question."""
        match = self._timeframe_pattern.search(question)
        if match:
            tf = match.group(1).lower().replace(" ", "")
            # Normalize to standard format
            if "min" in tf:
                return tf.replace("min", "m").replace("ute", "")
            elif "hour" in tf or "hr" in tf:
                return tf.replace("hour", "h").replace("hr", "h")
            return tf
        return None
