"""Load .env (if present) before any module reads environment variables."""
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional in production
    pass
