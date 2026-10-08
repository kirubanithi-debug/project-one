import os
import hashlib
import logging

def calculate_file_hash(file_path):
    """
    Calculate the SHA-256 hash of a file to detect duplicates.
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Read in chunks of 4096 bytes
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logging.error(f"Error calculating hash for {file_path}: {e}")
        return None
