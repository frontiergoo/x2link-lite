"""固定した実行時依存のライセンスと同梱通知を記録する。"""

import importlib.metadata as metadata
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent
folder = root / "docs" / "licenses"
folder.mkdir(parents=True, exist_ok=True)
rows = [
    "# 実行時依存ライブラリのライセンス",
    "",
    "インストール済み配布物のメタデータと通知ファイルを採録。依存ソースを変更・転記していない。",
    "",
    "|名前|版|ライセンス表記|",
    "|---|---|---|",
]
for line in (root / "requirements.txt").read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    name = line.split("==")[0]
    dist = metadata.distribution(name)
    license_name = (
        dist.metadata.get("License-Expression")
        or dist.metadata.get("License")
        or "同梱通知を参照"
    )
    rows.append(f"|{name}|{dist.version}|{license_name}|")
    for path in dist.files or []:
        if re.search(
            r"(^|/)(licen[cs]e[^/]*|copying[^/]*|notice[^/]*)$", str(path), re.I
        ):
            content = dist.locate_file(path).read_bytes()
            (folder / (name + "-" + str(path).replace("/", "_"))).write_bytes(content)
(root / "docs" / "依存ライセンス.md").write_text("\n".join(rows) + "\n")
print("依存ライセンスの一覧と同梱通知を記録しました。")
