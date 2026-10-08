import os
import logging
from datetime import datetime

# Setup Logs Folder
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

class SessionStats:
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.total_pdfs = 0
        self.successful_extractions = 0
        self.failed_files = [] # List of tuples: (filename, error_msg)
        self.skipped_files = [] # List of filenames skipped as duplicates

    def start_session(self, count):
        self.start_time = datetime.now()
        self.total_pdfs = count
        self.successful_extractions = 0
        self.failed_files = []
        self.skipped_files = []

    def end_session(self):
        self.end_time = datetime.now()

    def get_duration(self):
        if self.start_time and self.end_time:
            return str(self.end_time - self.start_time).split(".")[0]
        return "00:00:00"

    def generate_summary(self):
        duration = self.get_duration()
        summary = f"""
==================================================
EXTRACTION SESSION SUMMARY
==================================================
Start Time:             {self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}
End Time:               {self.end_time.strftime('%Y-%m-%d %H:%M:%S') if self.end_time else 'N/A'}
Total Duration:         {duration}
Total Files Found:      {self.total_pdfs}
Successful Extractions: {self.successful_extractions}
Skipped (Duplicates):   {len(self.skipped_files)}
Failed Extractions:     {len(self.failed_files)}
==================================================
"""
        if self.failed_files:
            summary += "\nFAILED FILES DETAILS:\n"
            for index, (file, err) in enumerate(self.failed_files, 1):
                summary += f"{index}. {file} -> {err}\n"
        
        if self.skipped_files:
            summary += "\nSKIPPED DUPLICATES:\n"
            for index, file in enumerate(self.skipped_files, 1):
                summary += f"{index}. {file}\n"
                
        summary += "==================================================\n"
        return summary


# Global stats instance
stats = SessionStats()

def setup_logging():
    # Setup log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOGS_DIR, f"extraction_run_{timestamp}.log")
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clean previous handlers
    if logger.handlers:
        logger.handlers = []

    # File Handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('[%(levelname)s]: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logging.info(f"Logging initialized. Log file: {log_file}")
    return log_file
