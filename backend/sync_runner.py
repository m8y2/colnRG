import sys
sys.path.insert(0, '.')

from database import init_db
from sync import run_sync
from clean_data import main as clean_main

init_db()
result = run_sync()
print(f'Sync completed: {result}')
clean_main()
print('Data cleaned.')
