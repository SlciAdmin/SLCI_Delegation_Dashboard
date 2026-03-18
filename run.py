#!/usr/bin/env python3
"""
SLCI Delegation Dashboard - Application Entry Point
"""
import os
from dotenv import load_dotenv

load_dotenv()

from app import app

if __name__ == "__main__":
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    port = int(os.getenv('PORT', 5000))
    
    print("=" * 60)
    print("🚀 SLCI Delegation Dashboard")
    print("=" * 60)
    print(f"📍 Running on: http://127.0.0.1:{port}")
    print(f"🔧 Debug Mode: {'ON' if debug else 'OFF'}")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=debug)