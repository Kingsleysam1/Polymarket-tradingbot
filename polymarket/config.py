# Configuration for Polymarket Market Making Bot
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class APIConfig:
    """API endpoints and credentials."""
    clob_host: str = "https://clob.polymarket.com"
    ws_host: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    chain_id: int = 137  # Polygon Mainnet
    
    private_key: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY", ""))
    funder_address: str = field(default_factory=lambda: os.getenv("FUNDER_ADDRESS", ""))
    signature_type: int = field(default_factory=lambda: int(os.getenv("SIGNATURE_TYPE", "0")))
    
    def validate(self) -> None:
        if not self.private_key:
            raise ValueError("PRIVATE_KEY environment variable is required")
        if not self.funder_address:
            raise ValueError("FUNDER_ADDRESS environment variable is required")


@dataclass
class TradingConfig:
    """Trading parameters and limits."""
    # Target markets (regex patterns)
    target_assets: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    target_timeframes: list[str] = field(default_factory=lambda: ["15m", "1h"])
    
    # Price range filter
    min_price: float = 0.20
    max_price: float = 0.80
    
    # Position limits
    max_position_usdc: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_USDC", "100")))
    max_position_per_market: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_PER_MARKET", "50")))
    
    # Quote parameters
    tick_size: float = 0.01  # Minimum price increment
    base_quote_size: float = 5.0  # Base shares per quote
    
    # Breakeven box
    breakeven_target: float = 0.99  # YES + NO cost target
    safety_margin: float = 0.005  # Additional margin buffer
    
    # Inventory skew thresholds
    skew_threshold: float = 1.2  # Trigger rebalancing when YES/NO > 1.2 or < 0.8
    
    # Timing
    quote_refresh_seconds: float = 0.5
    batch_size: int = 10


@dataclass
class WebSocketConfig:
    """WebSocket connection settings."""
    reconnect_base_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    reconnect_multiplier: float = 2.0
    heartbeat_interval: float = 30.0
    connection_timeout: float = 10.0


@dataclass
class PersistenceConfig:
    """State persistence settings."""
    state_file: str = field(default_factory=lambda: os.getenv("STATE_FILE", "state.json"))
    save_interval_seconds: float = 5.0
    enable_persistence: bool = True


@dataclass
class Config:
    """Main configuration container."""
    api: APIConfig = field(default_factory=APIConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    
    paper_trading: bool = field(default_factory=lambda: os.getenv("PAPER_TRADING_MODE", "false").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    
    def validate(self) -> None:
        """Validate all configuration."""
        if not self.paper_trading:
            self.api.validate()


def load_config() -> Config:
    """Load and validate configuration."""
    config = Config()
    config.validate()
    return config
