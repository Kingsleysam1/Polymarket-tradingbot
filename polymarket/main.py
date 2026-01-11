#!/usr/bin/env python3
"""
Polymarket HFT Market Making Bot

High-frequency market maker that asymmetrically accumulates YES/NO shares
while maintaining a breakeven box cost < $0.99.

Features:
- Post-only orders (never takes liquidity)
- Inventory skew management
- Real-time WebSocket orderbook updates
- State persistence for crash recovery
- Daily rebate tracking

Usage:
    python main.py                    # Production mode
    PAPER_TRADING_MODE=true python main.py  # Paper trading mode
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from datetime import datetime
from typing import Optional
import json
import os
from aiohttp import web
import aiohttp_cors

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

from config import load_config, Config
from models import (
    MarketInfo, Quote, Fill, Side, Outcome, OrderBook
)
from websocket_manager import WebSocketManager, OrderBookManager
from inventory_tracker import InventoryTracker
from breakeven_calculator import BreakevenCalculator
from quote_generator import QuoteGenerator, BatchQuoteBuilder
from market_filter import MarketFilter
from rebate_tracker import RebateTracker
from state_manager import StateManager


# Configure logging
def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


logger = logging.getLogger(__name__)


class DashboardAPI:
    """Lightweight API server for dashboard integration."""
    
    def __init__(self, bot: "MarketMakingBot", port: int = 8080):
        self.bot = bot
        self.port = port
        self.app = web.Application()
        self.runner = None
        self.site = None
        
        # Setup routes
        self.app.router.add_get('/api/stats', self.handle_stats)
        self.app.router.add_get('/api/fills', self.handle_fills)
        self.app.router.add_get('/api/positions', self.handle_positions)
        self.app.router.add_get('/api/markets', self.handle_markets)
        
        # Setup CORS
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        })
        
        for route in list(self.app.router.routes()):
            cors.add(route)
            
        # Serve dashboard
        # Get absolute path to dashboard directory (polymarketr/dashboard)
        # We are in polymarketr/polymarket/main.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        dashboard_dir = os.path.join(os.path.dirname(current_dir), 'dashboard')
        
        # Serve index at root
        self.app.router.add_get('/', self.handle_index)
        
        # Serve static files at root (registered LAST to allow API routes to match first)
        self.app.router.add_static('/', path=dashboard_dir, name='dashboard')

    async def handle_index(self, request):
        """Serve the dashboard index page."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        index_path = os.path.join(os.path.dirname(current_dir), 'dashboard', 'index.html')
        return web.FileResponse(index_path)
            
    async def start(self):
        """Start the API server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, 'localhost', self.port)
        await self.site.start()
        logger.info(f"Dashboard API listening on http://localhost:{self.port}")
        
    async def stop(self):
        """Stop the API server."""
        if self.runner:
            await self.runner.cleanup()
            
    async def handle_stats(self, request):
        """Return summary statistics."""
        state = self.bot.state_manager.state
        return web.json_response({
            "total_maker_volume": state.total_maker_volume,
            "total_rebates_estimate": state.total_rebates_estimate,
            "last_updated": state.last_updated.isoformat(),
            "active_markets_count": len(self.bot.active_markets),
            "fills_count": len(state.fills),
            "positions_count": len(state.positions)
        })
        
    async def handle_fills(self, request):
        """Return recent fills."""
        fills = self.bot.state_manager.get_fills()
        return web.json_response({
            "fills": [f.to_dict() for f in fills[-100:]]
        })
        
    async def handle_positions(self, request):
        """Return current positions."""
        positions = self.bot.state_manager.get_positions()
        return web.json_response({
            "positions": {k: v.to_dict() for k, v in positions.items()}
        })

    async def handle_markets(self, request):
        """Return active markets."""
        return web.json_response({
            "markets": [
                {
                    "condition_id": m.condition_id,
                    "question": m.question,
                    "yes_price": m.yes_price,
                    "no_price": m.no_price
                }
                for m in self.bot.active_markets.values()
            ]
        })


class MarketMakingBot:
    """
    Main Market Making bot orchestration.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Initialize CLOB client
        if config.paper_trading:
            logger.info("PAPER TRADING MODE - Orders will not be submitted")
            self.client = ClobClient(config.api.clob_host)
        else:
            self.client = ClobClient(
                config.api.clob_host,
                key=config.api.private_key,
                chain_id=config.api.chain_id,
                signature_type=config.api.signature_type,
                funder=config.api.funder_address
            )
            # Derive API credentials
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
        
        # Initialize components
        self.orderbook_manager = OrderBookManager()
        self.inventory_tracker = InventoryTracker(config.trading.skew_threshold)
        self.breakeven_calc = BreakevenCalculator(
            config.trading.breakeven_target,
            config.trading.safety_margin
        )
        self.quote_generator = QuoteGenerator(config.trading)
        self.market_filter = MarketFilter(
            config.trading.target_assets,
            config.trading.target_timeframes,
            config.trading.min_price,
            config.trading.max_price
        )
        self.rebate_tracker = RebateTracker()
        self.rebate_tracker = RebateTracker()
        self.state_manager = StateManager(config.persistence)
        self.dashboard_api = DashboardAPI(self)
        
        # WebSocket manager (initialized in start)
        self.ws_manager: Optional[WebSocketManager] = None
        
        # Active markets
        self.active_markets: dict[str, MarketInfo] = {}
        
        # Pending quotes (order_id -> Quote)
        self.pending_quotes: dict[str, Quote] = {}
    
    async def start(self) -> None:
        """Start the market making bot."""
        logger.info("=" * 60)
        logger.info("POLYMARKET MARKET MAKING BOT STARTING")
        logger.info("=" * 60)
        
        self._running = True
        
        # Load persisted state
        if self.state_manager.load():
            self.inventory_tracker.load_from_positions(
                self.state_manager.get_positions()
            )
        
        # Start state persistence
        self.state_manager.start()
        
        # Start Dashboard API
        await self.dashboard_api.start()
        
        # Fetch and filter markets
        await self._refresh_markets()
        
        if not self.active_markets:
            logger.warning("No eligible markets found, waiting for market refresh...")
        
        # Initialize WebSocket
        await self._init_websocket()
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start main loop
        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        finally:
            await self._shutdown()
    
    async def _init_websocket(self) -> None:
        """Initialize WebSocket connection."""
        creds = self.client.get_api_creds() if hasattr(self.client, 'get_api_creds') else None
        
        self.ws_manager = WebSocketManager(
            ws_url=self.config.api.ws_host,
            config=self.config.websocket,
            on_message=self._handle_ws_message,
            on_connected=self._on_ws_connected,
            on_disconnected=self._on_ws_disconnected,
            api_key=creds.api_key if creds else None,
            api_secret=creds.api_secret if creds else None,
            api_passphrase=creds.api_passphrase if creds else None
        )
        
        # Subscribe to market channels for active markets
        token_ids = []
        for market in self.active_markets.values():
            token_ids.extend([market.yes_token_id, market.no_token_id])
        
        if token_ids:
            await self.ws_manager.subscribe_market(token_ids)
        
        # Start WebSocket connection (runs in background)
        asyncio.create_task(self.ws_manager.connect())
        
        # Also subscribe to user channel for fill updates
        if creds:
            await self.ws_manager.subscribe_user()
    
    def _handle_ws_message(self, message: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = message.get("type") or message.get("event_type")
        
        # Route to orderbook manager for market data
        if msg_type in ("book", "price_change"):
            self.orderbook_manager.handle_message(message)
        
        # Handle fill notifications
        elif msg_type == "trade" or msg_type == "fill":
            self._handle_fill_message(message)
    
    def _handle_fill_message(self, message: dict) -> None:
        """Handle fill notification from WebSocket."""
        order_id = message.get("order_id") or message.get("orderId")
        
        if order_id not in self.pending_quotes:
            return
        
        quote = self.pending_quotes[order_id]
        fill_size = float(message.get("size", 0))
        fill_price = float(message.get("price", 0))
        
        if fill_size <= 0:
            return
        
        # Find condition_id for this token
        condition_id = None
        for cid, market in self.active_markets.items():
            if quote.token_id in (market.yes_token_id, market.no_token_id):
                condition_id = cid
                break
        
        if not condition_id:
            logger.warning(f"Could not find market for token {quote.token_id}")
            return
        
        # Create fill record
        fill = Fill(
            order_id=order_id,
            token_id=quote.token_id,
            outcome=quote.outcome,
            side=quote.side,
            price=fill_price,
            size=fill_size,
            maker=True
        )
        
        # Update inventory
        self.inventory_tracker.record_fill(condition_id, fill)
        
        # Record rebate
        self.rebate_tracker.record_fill(fill.notional, is_maker=True)
        
        # Update state
        self.state_manager.record_fill(fill)
        self.state_manager.update_positions(
            self.inventory_tracker.export_positions()
        )
        self.state_manager.update_rebates(
            self.rebate_tracker.get_total_rebates()
        )
        
        logger.info(
            f"FILL: {quote.outcome.value} {fill_size}@{fill_price:.4f} = "
            f"${fill.notional:.2f} | Box: "
            f"{self.inventory_tracker.get_box_cost(condition_id):.4f}"
        )
    
    def _on_ws_connected(self) -> None:
        """Handle WebSocket connected event."""
        logger.info("WebSocket connected")
    
    def _on_ws_disconnected(self) -> None:
        """Handle WebSocket disconnected event."""
        logger.warning("WebSocket disconnected, will reconnect...")
    
    async def _refresh_markets(self) -> None:
        """Fetch and filter eligible markets."""
        try:
            logger.info("Fetching markets from Polymarket...")
            
            # Get detailed markets (includes question field)
            response = self.client.get_markets(next_cursor="")
            markets_data = response.get("data", [])
            
            logger.info(f"Fetched {len(markets_data)} markets")
            
            # Parse and filter markets
            for m in markets_data:
                try:
                    # Skip closed or non-active markets
                    if not m.get("active") or m.get("closed"):
                        continue
                        
                    tokens = m.get("tokens", [])
                    if len(tokens) < 2:
                        continue
                    
                    # Find YES and NO tokens
                    yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
                    no_token = next((t for t in tokens if t.get("outcome") == "No"), None)
                    
                    if not yes_token or not no_token:
                        continue
                    
                    market = MarketInfo(
                        condition_id=m.get("condition_id", ""),
                        question=m.get("question", ""),
                        yes_token_id=yes_token.get("token_id", ""),
                        no_token_id=no_token.get("token_id", ""),
                        yes_price=float(yes_token.get("price", 0)),
                        no_price=float(no_token.get("price", 0)),
                        active=m.get("active", True)
                    )
                    
                    if self.market_filter.is_eligible(market):
                        self.active_markets[market.condition_id] = market
                        
                        # Initialize position tracker
                        self.inventory_tracker.get_or_create_position(
                            market.condition_id,
                            market.yes_token_id,
                            market.no_token_id
                        )
                        
                except Exception as e:
                    logger.debug(f"Error parsing market: {e}")
                    continue
            
            logger.info(f"Found {len(self.active_markets)} eligible markets")
            
            for market in self.active_markets.values():
                logger.info(f"  - {market.question[:60]}...")
                
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
    
    async def _main_loop(self) -> None:
        """Main trading loop."""
        logger.info("Starting main trading loop...")
        
        refresh_interval = 60  # Refresh markets every 60 seconds
        last_refresh = datetime.utcnow()
        
        while self._running and not self._shutdown_event.is_set():
            try:
                loop_start = datetime.utcnow()
                
                # Periodic market refresh
                if (loop_start - last_refresh).total_seconds() > refresh_interval:
                    await self._refresh_markets()
                    last_refresh = loop_start
                
                # Cancel existing orders before placing new ones
                await self._cancel_stale_orders()
                
                # Generate and submit quotes
                quotes = await self._generate_all_quotes()
                
                if quotes:
                    await self._submit_quotes(quotes)
                
                # Wait before next iteration
                elapsed = (datetime.utcnow() - loop_start).total_seconds()
                sleep_time = max(0, self.config.trading.quote_refresh_seconds - elapsed)
                
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=sleep_time
                )
                
            except asyncio.TimeoutError:
                # Normal timeout, continue loop
                pass
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause on error
    
    async def _generate_all_quotes(self) -> list[Quote]:
        """Generate quotes for all active markets."""
        all_quotes = []
        
        for condition_id, market in self.active_markets.items():
            try:
                # Get orderbooks
                yes_book = self.orderbook_manager.get_orderbook(market.yes_token_id)
                no_book = self.orderbook_manager.get_orderbook(market.no_token_id)
                
                # Get current position
                yes_qty = self.inventory_tracker.get_yes_quantity(condition_id)
                no_qty = self.inventory_tracker.get_no_quantity(condition_id)
                yes_avg = self.inventory_tracker.get_yes_avg_cost(condition_id)
                no_avg = self.inventory_tracker.get_no_avg_cost(condition_id)
                yes_spend = yes_qty * yes_avg
                no_spend = no_qty * no_avg
                
                # Calculate max bids (breakeven constraint)
                max_yes_bid = self.breakeven_calc.calculate_max_bid(
                    outcome=Outcome.YES,
                    total_spend_yes=yes_spend,
                    total_qty_yes=yes_qty,
                    avg_cost_no=no_avg,
                    total_spend_no=no_spend,
                    total_qty_no=no_qty,
                    avg_cost_yes=yes_avg,
                    new_qty=self.config.trading.base_quote_size
                )
                
                max_no_bid = self.breakeven_calc.calculate_max_bid(
                    outcome=Outcome.NO,
                    total_spend_yes=yes_spend,
                    total_qty_yes=yes_qty,
                    avg_cost_no=no_avg,
                    total_spend_no=no_spend,
                    total_qty_no=no_qty,
                    avg_cost_yes=yes_avg,
                    new_qty=self.config.trading.base_quote_size
                )
                
                # Generate quotes
                quotes = self.quote_generator.generate_quotes(
                    condition_id=condition_id,
                    yes_token_id=market.yes_token_id,
                    no_token_id=market.no_token_id,
                    yes_orderbook=yes_book,
                    no_orderbook=no_book,
                    yes_qty=yes_qty,
                    no_qty=no_qty,
                    max_yes_bid=max_yes_bid,
                    max_no_bid=max_no_bid
                )
                
                # Check position limits
                for quote in quotes:
                    total_spent = self.inventory_tracker.get_all_spent()
                    quote = self.quote_generator.adjust_size_for_position_limit(
                        quote,
                        total_spent,
                        self.config.trading.max_position_usdc
                    )
                    if quote:
                        all_quotes.append(quote)
                
            except Exception as e:
                logger.error(f"Error generating quotes for {condition_id[:8]}: {e}")
                continue
        
        return all_quotes
    
    async def _submit_quotes(self, quotes: list[Quote]) -> None:
        """Submit quotes to the exchange."""
        if self.config.paper_trading:
            for quote in quotes:
                logger.info(
                    f"[PAPER] Would place: {quote.outcome.value} BID "
                    f"{quote.size}@{quote.price:.4f}"
                )
            return
        
        try:
            # Build order args for batch submission
            order_args = []
            for quote in quotes:
                args = OrderArgs(
                    token_id=quote.token_id,
                    price=quote.price,
                    size=quote.size,
                    side=quote.side.value
                )
                order_args.append(args)
            
            if not order_args:
                return
            
            # Create signed orders
            signed_orders = []
            for args in order_args:
                signed = self.client.create_order(args)
                # Set post_only flag
                signed["post_only"] = True
                signed_orders.append(signed)
            
            # Submit batch
            if len(signed_orders) == 1:
                response = self.client.post_order(signed_orders[0], OrderType.GTC)
                responses = [response]
            else:
                # Use batch submission if available
                if hasattr(self.client, 'post_orders'):
                    responses = self.client.post_orders(signed_orders, OrderType.GTC)
                else:
                    responses = []
                    for order in signed_orders:
                        resp = self.client.post_order(order, OrderType.GTC)
                        responses.append(resp)
            
            # Track submitted orders
            for quote, resp in zip(quotes, responses):
                order_id = resp.get("orderID") or resp.get("order_id")
                if order_id:
                    quote.order_id = order_id
                    self.pending_quotes[order_id] = quote
                    logger.debug(f"Order placed: {order_id[:8]} - {quote.outcome.value}")
            
            logger.info(f"Submitted {len(quotes)} quotes")
            
        except Exception as e:
            logger.error(f"Failed to submit quotes: {e}")
    
    async def _cancel_stale_orders(self) -> None:
        """Cancel all open orders before placing new ones."""
        if self.config.paper_trading:
            return
        
        try:
            # Cancel all orders
            self.client.cancel_all()
            self.pending_quotes.clear()
            logger.debug("Cancelled all open orders")
        except Exception as e:
            logger.warning(f"Failed to cancel orders: {e}")
    
    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            self._running = False
            self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        
        # Cancel all orders
        if not self.config.paper_trading:
            try:
                self.client.cancel_all()
                logger.info("Cancelled all open orders")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")
        
        # Stop WebSocket
        if self.ws_manager:
            await self.ws_manager.disconnect()
            
        # Stop Dashboard API
        if hasattr(self, 'dashboard_api'):
            await self.dashboard_api.stop()
        
        # Stop state manager (does final save)
        await self.state_manager.stop()
        
        # Print summary
        logger.info("\n" + self.rebate_tracker.print_summary())
        
        logger.info("Shutdown complete")


async def main() -> None:
    """Main entry point."""
    # Load configuration
    config = load_config()
    
    # Setup logging
    setup_logging(config.log_level)
    
    # Create and run bot
    bot = MarketMakingBot(config)
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
