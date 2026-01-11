# State Manager for persistence and crash recovery
import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import BotState, MarketPosition, Fill
from config import PersistenceConfig

logger = logging.getLogger(__name__)


class StateManager:
    """
    Manages bot state persistence for crash recovery.
    
    Writes state to JSON file periodically with atomic operations.
    """
    
    def __init__(self, config: PersistenceConfig):
        self.config = config
        self.state_file = Path(config.state_file)
        self.state = BotState()
        self._save_lock = asyncio.Lock()
        self._save_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start(self) -> None:
        """Start periodic state saving."""
        if not self.config.enable_persistence:
            logger.info("State persistence disabled")
            return
        
        self._running = True
        self._save_task = asyncio.create_task(self._periodic_save())
        logger.info(f"State manager started, saving to {self.state_file}")
    
    async def stop(self) -> None:
        """Stop periodic saving and do final save."""
        self._running = False
        
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        
        # Final save
        await self.save()
        logger.info("State manager stopped")
    
    async def _periodic_save(self) -> None:
        """Periodically save state."""
        while self._running:
            await asyncio.sleep(self.config.save_interval_seconds)
            await self.save()
    
    async def save(self) -> None:
        """Save current state to file atomically."""
        if not self.config.enable_persistence:
            return
        
        async with self._save_lock:
            try:
                self.state.last_updated = datetime.utcnow()
                state_dict = self.state.to_dict()
                
                # Write to temp file first (atomic write pattern)
                temp_fd, temp_path = tempfile.mkstemp(
                    suffix=".json",
                    dir=self.state_file.parent
                )
                
                try:
                    with os.fdopen(temp_fd, 'w') as f:
                        json.dump(state_dict, f, indent=2, default=str)
                    
                    # Atomic rename
                    os.replace(temp_path, self.state_file)
                    
                    logger.debug(f"State saved: {len(self.state.positions)} positions")
                    
                except Exception as e:
                    # Clean up temp file on error
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
                    
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
    
    def load(self) -> bool:
        """
        Load state from file.
        
        Returns True if state was loaded, False if no state file exists.
        """
        if not self.config.enable_persistence:
            return False
        
        if not self.state_file.exists():
            logger.info("No existing state file, starting fresh")
            return False
        
        try:
            with open(self.state_file, 'r') as f:
                state_dict = json.load(f)
            
            self.state = BotState.from_dict(state_dict)
            
            logger.info(
                f"State loaded: {len(self.state.positions)} positions, "
                f"{len(self.state.fills)} fills, "
                f"last updated: {self.state.last_updated}"
            )
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse state file: {e}")
            # Backup corrupted file
            backup_path = self.state_file.with_suffix(".json.bak")
            os.rename(self.state_file, backup_path)
            logger.info(f"Corrupted state backed up to {backup_path}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return False
    
    def update_positions(self, positions: dict[str, MarketPosition]) -> None:
        """Update positions in state."""
        self.state.positions = positions
    
    def record_fill(self, fill: Fill) -> None:
        """Record a fill in state."""
        self.state.fills.append(fill)
        
        # Keep only last 1000 fills
        if len(self.state.fills) > 1000:
            self.state.fills = self.state.fills[-1000:]
        
        # Update maker volume
        if fill.maker:
            self.state.total_maker_volume += fill.notional
    
    def update_rebates(self, estimated_rebates: float) -> None:
        """Update estimated rebates."""
        self.state.total_rebates_estimate = estimated_rebates
    
    def get_positions(self) -> dict[str, MarketPosition]:
        """Get positions from state."""
        return self.state.positions
    
    def get_fills(self) -> list[Fill]:
        """Get fills from state."""
        return self.state.fills
    
    def get_total_maker_volume(self) -> float:
        """Get total maker volume."""
        return self.state.total_maker_volume
    
    def clear_state(self) -> None:
        """Clear all state (use with caution)."""
        self.state = BotState()
        if self.state_file.exists():
            # Backup before clearing
            backup_path = self.state_file.with_suffix(".json.cleared")
            os.rename(self.state_file, backup_path)
            logger.info(f"State cleared, old state backed up to {backup_path}")
