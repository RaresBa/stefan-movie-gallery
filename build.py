from pathlib import Path
from shutil import copytree, rmtree


def main():
    project_dir = Path(__file__).resolve().parent

    source = project_dir / "static"
    destination = project_dir / "public" / "static"

    if not source.is_dir():
        raise RuntimeError("The static folder is missing.")

    # This directory is generated from static/ during each build.
    if destination.exists():
        rmtree(destination)

    copytree(source, destination)

    print("Static assets prepared for Vercel.")


if __name__ == "__main__":
    main()