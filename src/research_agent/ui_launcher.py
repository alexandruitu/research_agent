import sys
from pathlib import Path


def main():
    from streamlit.web import cli

    app = Path(__file__).with_name("ui.py")
    sys.argv = [
        "streamlit",
        "run",
        str(app),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--theme.base",
        "light",
        "--theme.primaryColor",
        "#20644d",
        "--theme.textColor",
        "#19392f",
        *sys.argv[1:],
    ]
    cli.main()


if __name__ == "__main__":
    main()
