# In llm_fight/run.py
# import sys # No longer needed for sys.path
# from pathlib import Path # No longer needed for sys.path

# _project_root = str(Path(__file__).resolve().parent)
# if _project_root not in sys.path:
#     sys.path.insert(0, _project_root)

from src.cli import app # app from src.cli should have commands registered

if __name__ == "__main__":
    # Typer will use sys.argv automatically when app() is called
    # Remove diagnostic prints for this attempt
    app() 
