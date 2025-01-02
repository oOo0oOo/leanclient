import os


def find_lean_files_recursively(abs_path: str) -> list[str]:
    uris = []
    for root, __, files in os.walk(abs_path):
        for file in files:
            if file.endswith(".lean"):
                uris.append("file://" + os.path.join(root, file))
    return uris
