# Data models for Polymarket Market Making Bot
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class Outcome(Enum):
    """Market outcome type."""
    YES = "YES"
    NO = "NO"


@dataclass
class MarketInfo:
    """Information about a tradeable market."""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    min_tick_size: float = 0.01
    active: bool = True
    
    # Current market data
    yes_price: float = 0.0
    no_price: float = 0.0
    
    @property
    def token_id(self, outcome: Outcome) -> str:
        return self.yes_token_id if outcome == Outcome.YES else self.no_token_id
    
    def is_in_price_range(self, min_price: float, max_price: float) -> bool:
        """Check if both outcomes are within tradeable price range."""
        return (min_price <= self.yes_price <= max_price and
                min_price <= self.no_price <= max_price)


@dataclass
class OrderBookLevel:
    """Single price level in the orderbook."""
    price: float
    size: float
    
    def __post_init__(self):
        self.price = round(self.price, 4)
        self.size = round(self.size, 4)


@dataclass
class OrderBook:
    """L2 Order book for a token."""
    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def best_bid(self) -> Optional[float]:
        """Return best (highest) bid price."""
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        """Return best (lowest) ask price."""
        return self.asks[0].price if self.asks else None
    
    @property
    def best_bid_size(self) -> float:
        """Return size at best bid."""
        return self.bids[0].size if self.bids else 0.0
    
    @property
    def best_ask_size(self) -> float:
        """Return size at best ask."""
        return self.asks[0].size if self.asks else 0.0
    
    @property
    def midpoint(self) -> Optional[float]:
        """Calculate midpoint price."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def spread(self) -> Optional[float]:
        """Calculate bid-ask spread."""
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None
    
    def get_level(self, side: Side, level: int = 0) -> Optional[OrderBookLevel]:
        """Get price level (0 = best, 1 = second best, etc.)."""
        book = self.bids if side == Side.BUY else self.asks
        return book[level] if level < len(book) else None


@dataclass
class Position:
    """Position in a specific token."""
    token_id: str
    outcome: Outcome
    quantity: float = 0.0
    total_cost: float = 0.0  # Total USDC spent
    
    @property
    def avg_cost(self) -> float:
        """Average cost per share."""
        return self.total_cost / self.quantity if self.quantity > 0 else 0.0
    
    def add_fill(self, qty: float, price: float) -> None:
        """Update position with a new fill."""
        self.total_cost += qty * price
        self.quantity += qty
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "token_id": self.token_id,
            "outcome": self.outcome.value,
            "quantity": self.quantity,
            "total_cost": self.total_cost
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        """Deserialize from dictionary."""
        return cls(
            token_id=data["token_id"],
            outcome=Outcome(data["outcome"]),
            quantity=data["quantity"],
            total_cost=data["total_cost"]
        )


@dataclass
class MarketPosition:
    """Combined YES and NO positions for a market."""
    condition_id: str
    yes_position: Position
    no_position: Position
    
    @property
    def skew_ratio(self) -> float:
        """Calculate YES/NO quantity ratio. Returns 1.0 if NO is zero."""
        if self.no_position.quantity == 0:
            return float("inf") if self.yes_position.quantity > 0 else 1.0
        return self.yes_position.quantity / self.no_position.quantity
    
    @property
    def inverse_skew_ratio(self) -> float:
        """Calculate NO/YES quantity ratio. Returns 1.0 if YES is zero."""
        if self.yes_position.quantity == 0:
            return float("inf") if self.no_position.quantity > 0 else 1.0
        return self.no_position.quantity / self.yes_position.quantity
    
    @property
    def box_cost(self) -> float:
        """Cost to acquire 1 YES + 1 NO at current average costs."""
        return self.yes_position.avg_cost + self.no_position.avg_cost
    
    @property
    def total_usdc_spent(self) -> float:
        """Total USDC spent on this market."""
        return self.yes_position.total_cost + self.no_position.total_cost
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "condition_id": self.condition_id,
            "yes_position": self.yes_position.to_dict(),
            "no_position": self.no_position.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MarketPosition":
        """Deserialize from dictionary."""
        return cls(
            condition_id=data["condition_id"],
            yes_position=Position.from_dict(data["yes_position"]),
            no_position=Position.from_dict(data["no_position"])
        )


@dataclass
class Quote:
    """A quote to be placed in the market."""
    token_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float
    order_id: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        return self.order_id is not None
    
    def to_order_args(self) -> dict:
        """Convert to py-clob-client OrderArgs format."""
        return {
            "token_id": self.token_id,
            "price": self.price,
            "size": self.size,
            "side": self.side.value
        }


@dataclass
class Fill:
    """A filled order."""
    order_id: str
    token_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    maker: bool = True  # We should always be maker
    
    @property
    def notional(self) -> float:
        """USDC value of the fill."""
        return self.price * self.size
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "order_id": self.order_id,
            "token_id": self.token_id,
            "outcome": self.outcome.value,
            "side": self.side.value,
            "price": self.price,
            "size": self.size,
            "timestamp": self.timestamp.isoformat(),
            "maker": self.maker
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Fill":
        """Deserialize from dictionary."""
        return cls(
            order_id=data["order_id"],
            token_id=data["token_id"],
            outcome=Outcome(data["outcome"]),
            side=Side(data["side"]),
            price=data["price"],
            size=data["size"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            maker=data.get("maker", True)
        )


@dataclass
class BotState:
    """Complete bot state for persistence."""
    positions: dict[str, MarketPosition] = field(default_factory=dict)
    open_orders: dict[str, Quote] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    total_maker_volume: float = 0.0
    total_rebates_estimate: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "open_orders": {k: v.to_order_args() for k, v in self.open_orders.items()},
            "fills": [f.to_dict() for f in self.fills[-1000:]],  # Keep last 1000 fills
            "total_maker_volume": self.total_maker_volume,
            "total_rebates_estimate": self.total_rebates_estimate,
            "last_updated": self.last_updated.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BotState":
        """Deserialize from dictionary."""
        return cls(
            positions={k: MarketPosition.from_dict(v) for k, v in data.get("positions", {}).items()},
            open_orders={},  # Orders need to be reconstructed from API
            fills=[Fill.from_dict(f) for f in data.get("fills", [])],
            total_maker_volume=data.get("total_maker_volume", 0.0),
            total_rebates_estimate=data.get("total_rebates_estimate", 0.0),
            last_updated=datetime.fromisoformat(data["last_updated"]) if "last_updated" in data else datetime.utcnow()
        )
