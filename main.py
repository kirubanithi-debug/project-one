import tkinter as tk
from ui_manager import DrawingExtractorApp
import sys

def main():
    root = tk.Tk()
    app = DrawingExtractorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
