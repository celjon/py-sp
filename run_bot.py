#!/usr/bin/env python3
"""
Скрипт для запуска антиспам бота
"""

import sys
import os
from pathlib import Path

# Добавляем корневую директорию в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    from src.main import main
    import asyncio
    
    print("🤖 Anti-Spam Bot")
    print("=" * 50)
    
    asyncio.run(main())

