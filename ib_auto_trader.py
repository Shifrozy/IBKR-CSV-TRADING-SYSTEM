"""
Interactive Brokers Auto Trading System
Safe paper trading version for testing with ib_insync
"""

from ib_insync import *
import pandas as pd
import logging
from datetime import datetime
import time
import sys

# ============================================================================
# CONFIGURATION
# ============================================================================

# IB Connection Settings (Paper Trading)
IB_HOST = '127.0.0.1'
IB_PORT = 7497  # 7497 for TWS Paper, 7496 for TWS Live, 4002 for Gateway Paper
CLIENT_ID = 1

# File paths
CSV_FILE = 'Alg_ETF_Trading_Strategy-vol-target-2-Final_20251031 (1).csv'
LOG_FILE = f'trading_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

# Safety settings
PAPER_TRADING_ONLY = True  # Set to False only when ready for live trading
MAX_ORDER_SIZE = 1000  # Maximum shares per order (safety limit)

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure logging to both file and console"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# IB CONNECTION MANAGER
# ============================================================================

class IBConnectionManager:
    """Manages connection to Interactive Brokers"""
    
    def __init__(self, host, port, client_id):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        
    def connect(self):
        """Establish connection to IB TWS/Gateway"""
        try:
            logger.info(f"Connecting to IB at {self.host}:{self.port}...")
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            logger.info("✓ Successfully connected to Interactive Brokers")
            
            # Verify paper trading mode
            if PAPER_TRADING_ONLY:
                accounts = self.ib.managedAccounts()
                logger.info(f"Connected accounts: {accounts}")
                if accounts and not any('paper' in acc.lower() or 'df' in acc.lower() or 'du' in acc.lower() for acc in accounts):
                    logger.warning("⚠ WARNING: This may not be a paper trading account!")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to IB: {e}")
            logger.error("Make sure TWS or IB Gateway is running and API connections are enabled")
            return False
    
    def disconnect(self):
        """Safely disconnect from IB"""
        try:
            self.ib.disconnect()
            logger.info("Disconnected from IB")
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")

# ============================================================================
# ORDER PROCESSOR
# ============================================================================

class OrderProcessor:
    """Processes and places orders from CSV file"""
    
    def __init__(self, ib_connection):
        self.ib = ib_connection.ib
        
    def read_orders_from_csv(self, csv_file):
        """Read and parse orders from CSV file"""
        try:
            logger.info(f"Reading orders from CSV: {csv_file}")
            df = pd.read_csv(csv_file)
            logger.info(f"✓ Found {len(df)} orders in CSV")
            logger.info(f"Columns: {list(df.columns)}")
            return df
            
        except FileNotFoundError:
            logger.error(f"✗ CSV file not found: {csv_file}")
            return None
        except Exception as e:
            logger.error(f"✗ Error reading CSV: {e}")
            return None
    
    def create_contract(self, row):
        """Create IB contract object from CSV row"""
        try:
            contract = Stock(
                symbol=row['Symbol'],
                exchange=row['Exchange'].split('/')[0] if pd.notna(row.get('Exchange')) else 'SMART',
                currency=row.get('Currency', 'USD')
            )
            return contract
            
        except Exception as e:
            logger.error(f"Error creating contract for {row.get('Symbol', 'UNKNOWN')}: {e}")
            return None
    
    def create_order(self, row):
        """Create IB order object from CSV row"""
        try:
            action = row['Action'].upper()
            quantity = int(row['Quantity'])
            order_type = row.get('OrderType', 'MKT').upper()
            
            # Safety check
            if quantity > MAX_ORDER_SIZE:
                logger.warning(f"⚠ Order size {quantity} exceeds MAX_ORDER_SIZE {MAX_ORDER_SIZE}")
                return None
            
            # Create base order
            order = Order()
            order.action = action
            order.totalQuantity = quantity
            order.orderType = order_type
            
            # Add limit price if specified
            if order_type == 'LMT' and pd.notna(row.get('LmtPrice')):
                order.lmtPrice = float(row['LmtPrice'])
            
            # Add stop price if specified
            if order_type in ['STP', 'STP LMT'] and pd.notna(row.get('AuxPrice')):
                order.auxPrice = float(row['AuxPrice'])
            
            # Time in force
            order.tif = row.get('TimeInForce', 'DAY')
            
            # Add account if specified
            if pd.notna(row.get('Account')):
                order.account = row['Account']
            
            return order
            
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            return None
    
    def place_order(self, contract, order, symbol):
        """Place order with IB"""
        try:
            logger.info(f"{'='*60}")
            logger.info(f"Placing {order.action} order:")
            logger.info(f"  Symbol: {symbol}")
            logger.info(f"  Quantity: {order.totalQuantity}")
            logger.info(f"  Order Type: {order.orderType}")
            if order.orderType == 'LMT':
                logger.info(f"  Limit Price: ${order.lmtPrice}")
            logger.info(f"{'='*60}")
            
            # Place the order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait briefly for order to be acknowledged
            self.ib.sleep(1)
            
            logger.info(f"✓ Order placed successfully - Order ID: {trade.order.orderId}")
            logger.info(f"  Status: {trade.orderStatus.status}")
            
            return trade
            
        except Exception as e:
            logger.error(f"✗ Error placing order for {symbol}: {e}")
            return None
    
    def process_all_orders(self, csv_file):
        """Read CSV and process all orders"""
        df = self.read_orders_from_csv(csv_file)
        
        if df is None or df.empty:
            logger.warning("No orders to process")
            return []
        
        trades = []
        
        for idx, row in df.iterrows():
            logger.info(f"\nProcessing order {idx + 1}/{len(df)}...")
            
            # Create contract
            contract = self.create_contract(row)
            if contract is None:
                continue
            
            # Create order
            order = self.create_order(row)
            if order is None:
                continue
            
            # Place order
            trade = self.place_order(contract, order, row['Symbol'])
            if trade:
                trades.append(trade)
            
            # Small delay between orders
            time.sleep(0.5)
        
        logger.info(f"\n✓ Completed processing {len(trades)}/{len(df)} orders")
        return trades

# ============================================================================
# POSITION MANAGER
# ============================================================================

class PositionManager:
    """Fetches and displays current positions"""
    
    def __init__(self, ib_connection):
        self.ib = ib_connection.ib
    
    def fetch_positions(self):
        """Fetch current positions from IB"""
        try:
            logger.info("\nFetching current positions...")
            positions = self.ib.positions()
            
            if not positions:
                logger.info("No open positions found")
                return []
            
            logger.info(f"{'='*80}")
            logger.info(f"{'Symbol':<10} {'Quantity':>10} {'Avg Cost':>12} {'Market Value':>15} {'Unrealized P&L':>15}")
            logger.info(f"{'='*80}")
            
            for pos in positions:
                logger.info(
                    f"{pos.contract.symbol:<10} "
                    f"{pos.position:>10.0f} "
                    f"${pos.avgCost:>11.2f} "
                    f"${pos.position * pos.avgCost:>14.2f} "
                    f"${pos.position * (pos.avgCost - pos.avgCost):>14.2f}"  # P&L calculation
                )
            
            logger.info(f"{'='*80}\n")
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def fetch_account_summary(self):
        """Fetch account summary information"""
        try:
            logger.info("Fetching account summary...")
            
            # Request account summary
            summary = self.ib.accountSummary()
            
            if summary:
                logger.info(f"{'='*60}")
                logger.info("Account Summary:")
                
                key_metrics = ['NetLiquidation', 'TotalCashValue', 'BuyingPower', 'GrossPositionValue']
                for item in summary:
                    if item.tag in key_metrics:
                        logger.info(f"  {item.tag}: {item.value} {item.currency}")
                
                logger.info(f"{'='*60}\n")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error fetching account summary: {e}")
            return None

# ============================================================================
# MAIN TRADING SYSTEM
# ============================================================================

class AutoTradingSystem:
    """Main trading system orchestrator"""
    
    def __init__(self):
        self.connection = None
        self.order_processor = None
        self.position_manager = None
    
    def initialize(self):
        """Initialize all components"""
        logger.info("="*80)
        logger.info("IB AUTO TRADING SYSTEM - PAPER TRADING MODE")
        logger.info("="*80)
        
        if PAPER_TRADING_ONLY:
            logger.info("⚠ SAFETY MODE: Paper trading only")
        else:
            logger.warning("⚠⚠⚠ WARNING: Live trading mode enabled! ⚠⚠⚠")
        
        # Connect to IB
        self.connection = IBConnectionManager(IB_HOST, IB_PORT, CLIENT_ID)
        if not self.connection.connect():
            return False
        
        # Initialize processors
        self.order_processor = OrderProcessor(self.connection)
        self.position_manager = PositionManager(self.connection)
        
        return True
    
    def run(self, csv_file):
        """Execute the trading workflow"""
        try:
            # Show current positions before trading
            logger.info("\n--- BEFORE TRADING ---")
            self.position_manager.fetch_positions()
            self.position_manager.fetch_account_summary()
            
            # Process orders from CSV
            logger.info("\n--- PROCESSING ORDERS ---")
            trades = self.order_processor.process_all_orders(csv_file)
            
            # Wait for orders to be processed
            if trades:
                logger.info("\nWaiting for orders to be processed...")
                time.sleep(3)
            
            # Show updated positions after trading
            logger.info("\n--- AFTER TRADING ---")
            self.position_manager.fetch_positions()
            self.position_manager.fetch_account_summary()
            
            # Summary
            logger.info("\n" + "="*80)
            logger.info(f"TRADING SESSION SUMMARY")
            logger.info(f"Orders processed: {len(trades)}")
            logger.info(f"Log file: {LOG_FILE}")
            logger.info("="*80)
            
        except KeyboardInterrupt:
            logger.info("\n⚠ Trading interrupted by user")
        except Exception as e:
            logger.error(f"Error during trading: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Clean shutdown"""
        logger.info("\nShutting down...")
        if self.connection:
            self.connection.disconnect()
        logger.info("✓ System shutdown complete")

# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    
    # Safety confirmation for paper trading
    print("\n" + "="*80)
    print("IB AUTO TRADING SYSTEM")
    print("="*80)
    print(f"Mode: {'PAPER TRADING' if PAPER_TRADING_ONLY else 'LIVE TRADING'}")
    print(f"CSV File: {CSV_FILE}")
    print(f"IB Connection: {IB_HOST}:{IB_PORT}")
    print("="*80)
    
    response = input("\nDo you want to proceed? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Trading cancelled by user")
        return
    
    # Initialize and run system
    system = AutoTradingSystem()
    
    if system.initialize():
        system.run(CSV_FILE)
    else:
        logger.error("Failed to initialize trading system")

if __name__ == "__main__":
    main()