"""AQuA-QE AI Gateway — Entry point"""
import uvicorn
from backend.api.routes import app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
    )
