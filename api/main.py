"""Asset Manager — FastAPI application."""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import transactions, mm_transactions, mm_accounts, portfolio, ai

app = FastAPI(
    title="Asset Manager API",
    description="REST API for Asset Manager — portfolio tracker and money manager.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router,    prefix="/api/transactions",    tags=["Portfolio Transactions"])
app.include_router(mm_transactions.router, prefix="/api/mm/transactions", tags=["Money Manager Transactions"])
app.include_router(mm_accounts.router,     prefix="/api/mm/accounts",     tags=["Money Manager Accounts"])
app.include_router(portfolio.router,       prefix="/api/portfolio",       tags=["Portfolio"])
app.include_router(ai.router,              prefix="/api/ai",              tags=["AI"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
