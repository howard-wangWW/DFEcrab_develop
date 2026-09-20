"""Logger utility"""
import logging

def get_logger(name: str):
    """Get a logger instance"""
    return logging.getLogger(name)
