"""Entry point — запускается через `python run.py` или `run.bat`."""
import os
import sys

# ensure utf-8 on Windows
if sys.platform.startswith('win'):
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from app import create_app

app = create_app()

if __name__ == '__main__':
    print()
    print('  GolfAdmin  —  http://127.0.0.1:5000')
    print('  Admins    :  admin / admin, manager / manager, cashier / cashier')
    print()
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
