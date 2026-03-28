try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass
