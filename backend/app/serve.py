"""Container entry point. Run migrations explicitly before starting the service."""
import os
import uvicorn
from .config import settings


def main():
    port = int(os.environ.get('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    uvicorn.run('app.main:app', host='0.0.0.0', port=port, workers=1,
                proxy_headers=True, forwarded_allow_ips=settings().forwarded_allow_ips,
                timeout_graceful_shutdown=60, access_log=False)


if __name__ == '__main__':
    main()
