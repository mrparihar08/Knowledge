import json
import os
import hashlib
from datetime import datetime

# Define a local file to act as our "Chain" or Audit Log
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_PATH = os.path.join(BASE_DIR, "local_ledger.json")

def _get_last_hash():
    """Helper to simulate chain linking."""
    if not os.path.exists(LEDGER_PATH):
        return "0" * 64
    with open(LEDGER_PATH, "r") as f:
        ledger = json.load(f)
        return ledger[-1]["tx_hash"] if ledger else "0" * 64

def get_tourist_from_ledger(tourist_id: str):
    """
    Searches the local ledger for a specific Digital Tourist ID.
    """
    if not os.path.exists(LEDGER_PATH):
        return None
    with open(LEDGER_PATH, "r") as f:
        ledger = json.load(f)
        # Return the most recent entry for this tourist ID
        for entry in reversed(ledger):
            if entry["tourist_id"] == tourist_id:
                return entry
    return None

def record_tourist_id_on_chain(tourist_id: str, duration_days: int = 30):
    """
    Simulates registering a tourist ID on a tamper-proof ledger.
    Replaces web3 with local cryptographic hashing.
    """
    try:
        # 1. Create a data block
        prev_hash = _get_last_hash()
        timestamp = datetime.utcnow().isoformat()
        payload = f"{prev_hash}{tourist_id}{timestamp}{duration_days}"
        
        # 2. Generate a 'Transaction Hash' (SHA-256)
        tx_hash = hashlib.sha256(payload.encode()).hexdigest()
        
        # 3. Save to local audit log (Simulated Ledger)
        new_block = {
            "tourist_id": tourist_id,
            "valid_until": timestamp, # Simplified duration logic
            "tx_hash": tx_hash,
            "previous_hash": prev_hash,
            "timestamp": timestamp,
            "status": "COMMITTED"
        }
        
        ledger = []
        if os.path.exists(LEDGER_PATH):
            with open(LEDGER_PATH, "r") as f:
                ledger = json.load(f)
        
        ledger.append(new_block)
        with open(LEDGER_PATH, "w") as f:
            json.dump(ledger, f, indent=4)

        return {
            "status": "success",
            "tx_hash": tx_hash,
            "block_number": len(ledger),
            "method": "Local_Cryptographic_Ledger"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }