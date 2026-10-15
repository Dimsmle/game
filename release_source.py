"""Build a source-only release from explicit source/document file classes."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parent
TOP_SUFFIXES={".py",".md",".txt",".bat"}
TREE_SUFFIXES={"studio":{ ".py",".js",".css",".html"},"tests":{".py",".js"},"docs":{".md"},"tools":{".py"}}


def is_private_file(path):
    return path.name.lower().startswith('local_secrets.') and path.name.lower()!='local_secrets.example.json'


def source_files(root=ROOT):
    root=Path(root)
    files=[p for p in root.iterdir() if p.is_file() and not p.is_symlink()
           and (p.name in {"VERSION",".gitignore","local_secrets.example.json"} or p.suffix in TOP_SUFFIXES)]
    for folder,extensions in TREE_SUFFIXES.items():
        for path in (root/folder).rglob("*"):
            parts=path.relative_to(root).parts
            if (path.is_file() and not path.is_symlink() and path.suffix in extensions
                and not any(x.startswith(".") or x in {"data","__pycache__","node_modules"} for x in parts)):
                files.append(path)
    return sorted((path for path in files if not is_private_file(path)),key=lambda p:p.relative_to(root).as_posix())


def main():
    version=(ROOT/"VERSION").read_text().strip()
    folder=ROOT/"releases";folder.mkdir(exist_ok=True)
    target=folder/("CharacterStudio_v"+version+"_source.zip")
    files=source_files()
    manifest=[]
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            rel=path.relative_to(ROOT).as_posix()
            archive.write(path,"CharacterStudio/"+rel)
            manifest.append({"path":rel,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (folder/(target.stem+".manifest.json")).write_text(json.dumps(
        {"version":version,"archive_sha256":digest,"file_count":len(files),"files":manifest},
        ensure_ascii=False,indent=2),encoding="utf-8")
    print(target);print("files=",len(files));print("sha256=",digest)


if __name__=="__main__":main()
