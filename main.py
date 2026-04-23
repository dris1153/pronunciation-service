"""Entry point — run with: python main.py  or  uvicorn main:app

.. important::

   This service uses ``@lru_cache`` singletons for ML model services
   (ASR, IPA, GOP, Prosody).  Each uvicorn *worker* is a separate process
   with its own memory space — so every worker loads its own copy of the
   ~94 MB / ~1.2 GB model.  Always run with ``--workers 1`` (the default)
   unless you have sufficient RAM for N copies of the model.
"""
from __future__ import annotations

import uvicorn

from app.application import create_app
from app.core.config import get_settings

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
