"""Entry point: python -m services.doc_converter"""
import uvicorn


def main() -> None:
    uvicorn.run(
        "services.doc_converter.main:app",
        host="0.0.0.0",
        port=8100,
        log_level="info",
    )


if __name__ == "__main__":
    main()
