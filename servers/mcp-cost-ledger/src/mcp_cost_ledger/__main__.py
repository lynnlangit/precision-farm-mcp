from .server import mcp


def main() -> None:
    # No banner or update-check box on every question (stdio child of farm-cli).
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
