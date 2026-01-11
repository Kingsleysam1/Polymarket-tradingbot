# WebSocket Manager for real-time orderbook updates
import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional, Any
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import WebSocketConfig

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connection to Polymarket CLOB.
    Handles auto-reconnection with exponential backoff.
    """
    
    def __init__(
        self,
        ws_url: str,
        config: WebSocketConfig,
        on_message: Callable[[dict], None],
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None
    ):
        self.ws_url = ws_url
        self.config = config
        self.on_message = on_message
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        
        # Auth credentials (optional, for user channel)
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        
        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_delay = config.reconnect_base_delay
        self._subscriptions: list[dict] = []
        self._last_message_time: Optional[datetime] = None
        
        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
    
    @property
    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        # websockets v16+ uses .state instead of .open
        try:
            from websockets import State
            return self._ws.state == State.OPEN
        except (ImportError, AttributeError):
            # Fallback for older versions
            return hasattr(self._ws, 'open') and self._ws.open
    
    async def connect(self) -> None:
        """Start the WebSocket connection."""
        self._running = True
        await self._connect_loop()
    
    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        logger.info("WebSocket disconnected")
    
    async def subscribe_market(self, token_ids: list[str]) -> None:
        """Subscribe to market channel for orderbook updates."""
        if not token_ids:
            return
        
        subscription = {
            "type": "subscribe",
            "channel": "market",
            "assets_ids": token_ids
        }
        
        self._subscriptions.append(subscription)
        
        if self.is_connected:
            await self._send(subscription)
            logger.info(f"Subscribed to market channel for {len(token_ids)} tokens")
    
    async def subscribe_user(self) -> None:
        """Subscribe to user channel for order updates (requires auth)."""
        if not all([self.api_key, self.api_secret, self.api_passphrase]):
            logger.warning("Cannot subscribe to user channel: missing credentials")
            return
        
        subscription = {
            "type": "subscribe",
            "channel": "user",
            "auth": {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "passphrase": self.api_passphrase
            }
        }
        
        self._subscriptions.append(subscription)
        
        if self.is_connected:
            await self._send(subscription)
            logger.info("Subscribed to user channel")
    
    async def unsubscribe_market(self, token_ids: list[str]) -> None:
        """Unsubscribe from market channel."""
        if not self.is_connected:
            return
        
        await self._send({
            "type": "unsubscribe",
            "channel": "market",
            "assets_ids": token_ids
        })
    
    async def _connect_loop(self) -> None:
        """Main connection loop with auto-reconnect."""
        while self._running:
            try:
                await self._establish_connection()
                self._reconnect_delay = self.config.reconnect_base_delay
                
                # Start receive and heartbeat tasks
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                # Wait for receive task to complete (disconnect or error)
                await self._receive_task
                
            except (ConnectionClosed, WebSocketException, OSError) as e:
                logger.warning(f"WebSocket connection error: {e}")
            except Exception as e:
                logger.error(f"Unexpected WebSocket error: {e}", exc_info=True)
            
            if self._running:
                if self.on_disconnected:
                    self.on_disconnected()
                
                logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
                await asyncio.sleep(self._reconnect_delay)
                
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * self.config.reconnect_multiplier,
                    self.config.reconnect_max_delay
                )
    
    async def _establish_connection(self) -> None:
        """Establish WebSocket connection and resubscribe."""
        logger.info(f"Connecting to {self.ws_url}")
        
        self._ws = await asyncio.wait_for(
            websockets.connect(
                self.ws_url,
                ping_interval=self.config.heartbeat_interval,
                ping_timeout=10
            ),
            timeout=self.config.connection_timeout
        )
        
        logger.info("WebSocket connected")
        
        # Resubscribe to all channels
        for subscription in self._subscriptions:
            await self._send(subscription)
            logger.debug(f"Resubscribed to {subscription.get('channel', 'unknown')} channel")
        
        if self.on_connected:
            self.on_connected()
    
    async def _receive_loop(self) -> None:
        """Receive and dispatch messages."""
        while self._running and self.is_connected:
            try:
                message = await self._ws.recv()
                self._last_message_time = datetime.utcnow()
                
                try:
                    data = json.loads(message)
                    self.on_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse message: {message[:100]}")
                    
            except ConnectionClosed:
                logger.info("WebSocket connection closed")
                break
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                break
    
    async def _heartbeat_loop(self) -> None:
        """Monitor connection health."""
        while self._running and self.is_connected:
            await asyncio.sleep(self.config.heartbeat_interval)
            
            # Check if we've received messages recently
            if self._last_message_time:
                silence = (datetime.utcnow() - self._last_message_time).total_seconds()
                if silence > self.config.heartbeat_interval * 2:
                    logger.warning(f"No messages for {silence:.0f}s, connection may be stale")
    
    async def _send(self, data: dict) -> None:
        """Send a message."""
        if self.is_connected:
            await self._ws.send(json.dumps(data))


class OrderBookManager:
    """
    Manages orderbook state from WebSocket updates.
    """
    
    def __init__(self):
        from models import OrderBook, OrderBookLevel
        
        self._orderbooks: dict[str, OrderBook] = {}
        self._lock = asyncio.Lock()
    
    def handle_message(self, message: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = message.get("type") or message.get("event_type")
        
        if msg_type == "book":
            self._handle_book_snapshot(message)
        elif msg_type == "price_change":
            self._handle_price_change(message)
        elif msg_type == "trade":
            # Trade messages can be used for tracking but don't update orderbook
            pass
        elif msg_type == "subscribed":
            logger.info(f"Successfully subscribed: {message}")
        elif msg_type == "error":
            logger.error(f"WebSocket error: {message}")
    
    def _handle_book_snapshot(self, message: dict) -> None:
        """Handle full orderbook snapshot."""
        from models import OrderBook, OrderBookLevel
        
        token_id = message.get("asset_id") or message.get("market")
        if not token_id:
            return
        
        bids = [
            OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
            for level in message.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
            for level in message.get("asks", [])
        ]
        
        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        
        self._orderbooks[token_id] = OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks
        )
        
        logger.debug(f"Book snapshot for {token_id}: {len(bids)} bids, {len(asks)} asks")
    
    def _handle_price_change(self, message: dict) -> None:
        """Handle incremental price change update."""
        from models import OrderBook, OrderBookLevel
        
        token_id = message.get("asset_id") or message.get("market")
        if not token_id:
            return
        
        # Get or create orderbook
        if token_id not in self._orderbooks:
            self._orderbooks[token_id] = OrderBook(token_id=token_id)
        
        book = self._orderbooks[token_id]
        
        # Process changes
        for change in message.get("changes", []):
            side = change.get("side", "").upper()
            price = float(change.get("price", 0))
            size = float(change.get("size", 0))
            
            if side == "BUY":
                self._update_level(book.bids, price, size, ascending=False)
            elif side == "SELL":
                self._update_level(book.asks, price, size, ascending=True)
        
        book.timestamp = datetime.utcnow()
    
    def _update_level(
        self,
        levels: list,
        price: float,
        size: float,
        ascending: bool
    ) -> None:
        """Update or insert a price level."""
        from models import OrderBookLevel
        
        # Find existing level
        for i, level in enumerate(levels):
            if abs(level.price - price) < 0.0001:
                if size <= 0:
                    levels.pop(i)
                else:
                    level.size = size
                return
        
        # Insert new level if size > 0
        if size > 0:
            new_level = OrderBookLevel(price=price, size=size)
            levels.append(new_level)
            
            # Re-sort
            if ascending:
                levels.sort(key=lambda x: x.price)
            else:
                levels.sort(key=lambda x: x.price, reverse=True)
    
    def get_orderbook(self, token_id: str) -> Optional[Any]:
        """Get orderbook for a token."""
        return self._orderbooks.get(token_id)
    
    def get_best_bid(self, token_id: str) -> Optional[float]:
        """Get best bid price for a token."""
        book = self._orderbooks.get(token_id)
        return book.best_bid if book else None
    
    def get_best_ask(self, token_id: str) -> Optional[float]:
        """Get best ask price for a token."""
        book = self._orderbooks.get(token_id)
        return book.best_ask if book else None
    
    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        book = self._orderbooks.get(token_id)
        return book.midpoint if book else None
